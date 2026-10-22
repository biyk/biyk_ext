# diagnostics/stage9_arch_experiments.py — ЭТАП 9, часть C: выразительность архитектуры.
#
# Тот же фиксированный split/seed/ init, что у B0 (этап 8 / stage9 b0). ВАРИАНТЫ:
#   A0 = текущая архитектура (ссылка на stage9_b0_joint — не пересчитываем);
#   A1 = текущий граф, бо́льшая ёмкость (hidden 96->192, head 24->48) — чистый cfg, ядро не
#        тронут; сравнивает «хватает лиWidth» без смены закона скоринга;
#   A2 = ЭКСПЕРИМЕНТАЛЬНАЯ копия (здесь, в ядро НЕ переносится): оценка ДОПУСТИМОЙ ТРОЙКИ
#        plan×target×weapon одним совместным MLP по [ствол ; вектор клетки ; вектор цели ;
#        вектор оружия] — вместо аддитивной суммы логов трёх голов. Joint NLL по A(s) и
#        argmax считаются по этому же скорингу (то, что этапы 7–8 называют joint-политикой,
#        но без факторизации на головы). value-head та же линейная по стволу, value_w=0.5.
# Критерии равнения: train/val joint NLL, val joint decode accuracy; ПЕРЕОБУЧЕНИЕ — отдельно
# (train улучшился, val нет — это НЕ довод «нужно больше ёмкости»).
import copy
import json
import math
import os
import random
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))     # server/
sys.path.insert(0, _HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from arent import dataset, joint, net, paths, scores, splitting, spec3, train
from arent.pure_net import PurePolicy, _dot, _lin, _relu, _zeros_like

SERVER = os.path.dirname(_HERE)
STAGE6_WS = os.path.join(SERVER, "stage6_out")
OUT_WS = os.path.join(SERVER, "stage9_out")
DATASET_NAME = "stage6_v3"
EPOCHS = 12
BATCH = 32
SEED = 20261022


# ---------------------------------------------------------------- A2: совместный тройный MLP
class TripleScorer:
    """S(p,t,w) = xU·relu(xW·[t ; cellvec_p ; tgtvec_t ; wpnvec_w] + xb) + xub; value — как в B0.

    Начальные ствол/линейка стоимости — ДЕТИТЕРМИНИРОВАННЫЙ net.init_params(cfg) (тот же
    cfg.seed, что у A0/A1). x-веса — из random.Random(cfg.seed): идентичны между запусками.
    """

    name = "pure_triple_exp"

    def __init__(self, cfg, dims):
        self.cfg = cfg
        self.dims = dims
        base = net.init_params(cfg, dims)
        self.params = {"trunk1": base["trunk1"], "b1": base["b1"], "trunk2": base["trunk2"],
                       "b2": base["b2"], "valueW": base["valueW"], "valueB": base["valueB"]}
        rng = random.Random(cfg.seed)
        hx = cfg.head
        cols = cfg.head + dims["cell_feat"] + dims["tgt_feat"] + dims["wpn_feat"]
        self.params["xW"] = [[round(rng.uniform(-1 / math.sqrt(cols), 1 / math.sqrt(cols)), 6)
                              for _ in range(cols)] for _ in range(hx)]
        self.params["xb"] = [0.0] * hx
        self.params["xU"] = [round(rng.uniform(-0.1, 0.1), 6) for _ in range(hx)]
        self.params["xub"] = 0.0
        self.grad = _zeros_like(self.params)
        self.vel = _zeros_like(self.params)

    def _trunk(self, state):
        p = self.params
        a1 = _relu(_lin(p["trunk1"], p["b1"], state))
        return a1, _relu(_lin(p["trunk2"], p["b2"], a1))


# ---------------------------------------------------------------- шаг обучения A2
def _a2_step(model, batch, lr):
    """Один SGD-шаг A2: joint NLL по собств. тройному скорингу + value-член как в B0.

    dS/loss = pr − onehot (softmax по всем тройкам A(s)); backward MLP по каждому троию;
    вклад в ствол — из первых cfg.head компонент входа (t) плюс value-градиент dt.
    """
    report = {"loss": 0.0, "value": 0.0}
    p, g = model.params, model.grad
    n_trunk = model.cfg.head
    for s in batch:
        a1_pre = _lin(p["trunk1"], p["b1"], s["state"])
        a1 = _relu(a1_pre)
        z2 = _lin(p["trunk2"], p["b2"], a1)
        t = _relu(z2)
        dt = [0.0] * len(t)
        ip, it, iw = joint.ensure_jointly_legal(s, spec3.SCHEMA)
        legal = s["legal"]
        rows = []
        vals = []
        for pos in range(len(legal)):
            for tt in range(len(legal[pos])):
                for ww in range(len(legal[pos][tt])):
                    if legal[pos][tt][ww]:
                        inp = t + s["cells"][pos] + s["targets"][tt] + s["weapons"][ww]
                        h = _relu(_lin(p["xW"], p["xb"], inp))
                        sc = p["xub"] + _dot(p["xU"], h)
                        rows.append(((pos, tt, ww), sc, h, inp))
                        vals.append(sc)
        top = max(vals)
        exps = [math.exp(v - top) for v in vals]
        ssum = sum(exps) or 1e-30
        logZ = top + math.log(ssum)
        lab = {(ip, it, iw)}
        lab_sc = next(sc for k, sc, _h, _i in rows if k in lab)
        report["loss"] += logZ - lab_sc
        for (pos, tt, ww), sc, h, inp in rows:
            dS = math.exp(sc - top) / ssum - (1.0 if (pos, tt, ww) in lab else 0.0)
            if not dS:
                continue
            g["xub"] += dS
            for r in range(len(h)):
                g["xU"][r] += dS * h[r]
                if h[r] <= 0.0:
                    continue
                dh = dS * p["xU"][r]
                g["xb"][r] += dh
                for c in range(len(inp)):
                    g["xW"][r][c] += dh * inp[c]
                # ствол = первые n_trunk компонент inp
                for j in range(n_trunk):
                    dt[j] += dh * p["xW"][r][j]
        value = p["valueB"] + _dot(p["valueW"], t)
        diff = value - float(s.get("value", 0.0))
        dv = model.cfg.value_w * diff
        report["value"] += abs(diff)
        report["loss"] += 0.5 * model.cfg.value_w * diff * diff
        report["vmse"] = report.get("vmse", 0.0) + diff * diff   # для потер-репорт как у B0
        for j in range(len(p["valueW"])):
            g["valueW"][j] += dv * t[j]
            dt[j] += dv * p["valueW"][j]
        g["valueB"] += dv
        PurePolicy._trunk_backward(model, s["state"], a1_pre, a1, z2, dt)
    n = max(1, len(batch))
    _a2_update(model, lr / n)
    scaled = {k: round(v / n, 4) for k, v in report.items()}
    scaled["n"] = n
    return scaled


def _a2_update(model, lr):
    p, g, v, cfg = model.params, model.grad, model.vel, model.cfg
    for key in ("trunk1", "trunk2", "xW"):
        for i, row in enumerate(p[key]):
            model_sgd(model, row, g[key][i], v[key][i], lr)
    for key in ("b1", "b2", "valueW", "xb", "xU"):
        model_sgd(model, p[key], g[key], v[key], lr)
    p["valueB"], v["valueB"] = scalar_sgd(model, p["valueB"], g["valueB"], v["valueB"], lr)
    p["xub"], v["xub"] = scalar_sgd(model, p["xub"], g["xub"], v["xub"], lr)
    g["xub"] = 0.0
    g["valueB"] = 0.0


def model_sgd(model, w, gw, vw, lr):
    m, wd = model.cfg.momentum, model.cfg.weight_decay
    for i in range(len(w)):
        vw[i] = m * vw[i] + gw[i] + wd * w[i]
        w[i] -= lr * vw[i]
        gw[i] = 0.0


def scalar_sgd(model, w, gw, vw, lr):
    v = model.cfg.momentum * vw + gw + model.cfg.weight_decay * w
    return w - lr * v, v


def _a2_eval(model, samples):
    """joint NLL и argmax-accuracy по СОБСТВЕННОМУ тройному скорингу (не по аддитивным головам)."""
    p = model.params
    nll_tot, acc, n = 0.0, 0, 0
    for s in samples:
        _a1, t = model._trunk(s["state"])
        ip, it, iw = joint.ensure_jointly_legal(s, spec3.SCHEMA)
        legal = s["legal"]
        vals, lab = [], None
        for pos in range(len(legal)):
            for tt in range(len(legal[pos])):
                for ww in range(len(legal[pos][tt])):
                    if legal[pos][tt][ww]:
                        sc = p["xub"] + _dot(p["xU"], _relu(_lin(
                            p["xW"], p["xb"],
                            t + s["cells"][pos] + s["targets"][tt] + s["weapons"][ww])))
                        vals.append((sc, (pos, tt, ww)))
                        if (pos, tt, ww) == (ip, it, iw):
                            lab = sc
        if lab is None or not vals:
            raise RuntimeError("метка вне A(s) в A2")
        top = max(v for v, _k in vals)
        ssum = sum(math.exp(v - top) for v, _k in vals) or 1e-30
        nll_tot += top + math.log(ssum) - lab
        best = max(vals)[1]
        acc += int(best == (ip, it, iw))
        n += 1
    value_mae = sum(abs((p["valueB"] + _dot(p["valueW"], model._trunk(s["state"])[1]))
                        - float(s["value"])) for s in samples) / max(1, n)
    return {"joint_nll": round(nll_tot / max(1, n), 5),
            "joint_decode_accuracy": round(acc / max(1, n), 3),
            "value_mae": round(value_mae, 4), "n": n}


def _big_cfg(cfg):
    c = copy.deepcopy(cfg)
    c.hidden, c.head = 192, 48
    return c


# ---------------------------------------------------------------- прогоны
def main() -> int:
    os.makedirs(OUT_WS, exist_ok=True)
    prev = paths.workspace()
    paths.set_workspace(STAGE6_WS)
    try:
        samples = dataset.load(DATASET_NAME)
    finally:
        paths.set_workspace(prev)
    paths.set_workspace(OUT_WS)
    out = {}
    try:
        train_set, val, rep = splitting.split_grouped(samples, frac=0.85, seed=SEED, strict=True)
        cfg = net.Config(schema=spec3.SCHEMA, kind="pure", device="cpu", epochs=EPOCHS,
                         batch=BATCH, val_frac=0.85, seed=SEED)
        # A0: ссылка на B0 (тот же код/данные/seed, этап 9 уже прогонял его)
        a0_path = os.path.join(OUT_WS, "stage9_value_ablations.json")
        out["A0_source"] = a0_path if os.path.exists(a0_path) else None

        # ---------------- A1: бо́льшая ёмкость (только cfg, ядро не тронуто)
        # ВАЖНО: train.run МУТИРУЕТ cfg (hidden/head) — передаём копию, иначе A2 получил бы
        # уже увеличенный ствол и равнение A2 vs A0 было бы нечестным.
        t0 = time.monotonic()
        r1 = train.run(name="stage9_a1_capacity", samples=train_set, val=val,
                       cfg=copy.deepcopy(cfg), epochs=EPOCHS, batch=BATCH,
                       hidden=192, head=48)
        out["A1"] = {"params": net.param_count(_big_cfg(cfg)), "params_A0": net.param_count(cfg),
                     "seconds": round(time.monotonic() - t0, 1),
                    "best_epoch": r1["summary"]["best_epoch"],
                    "best_val": r1["summary"]["best"], "final_val": r1["summary"]["val"],
                    "final_train": r1["summary"]["train"],
                    "history": [{"epoch": r["epoch"], "val_joint_nll": r["val"]["joint_nll"],
                                 "val_decode": r["val"]["joint_decode_accuracy"],
                                 "train_joint_nll": r["train"]["joint_nll"],
                                 "train_decode": r["train"]["joint_decode_accuracy"]}
                                for r in r1["history"]]}

        # ---------------- A2: совместный тройный скоринг (экспериментальная копия)
        d3 = net.dims_for(3)
        dims = {"cell_feat": net.slot_size("cells", 3),
                "tgt_feat": net.slot_size("targets", 3),
                "wpn_feat": net.slot_size("weapons", 3), "state": d3["state"]}
        model = TripleScorer(cfg, dims)
        lr = max(cfg.lr, 0.05)
        rng = random.Random(cfg.seed)
        hist = []
        best = None
        t0 = time.monotonic()
        for epoch in range(1, EPOCHS + 1):
            order = list(train_set)
            rng.shuffle(order)
            reps = [_a2_step(model, order[i:i + BATCH], lr) for i in range(0, len(order), BATCH)]
            tr_m = _a2_eval(model, train_set)
            va_m = _a2_eval(model, val)
            row = {"epoch": epoch,
                   "loss": round(sum(r["loss"] * r["n"] for r in reps) /
                                 sum(r["n"] for r in reps), 4),
                   "train": tr_m, "val": va_m}
            hist.append(row)
            print(f"A2 epoch {epoch}: train nll={tr_m['joint_nll']} decode={tr_m['joint_decode_accuracy']}"
                  f" | val nll={va_m['joint_nll']} decode={va_m['joint_decode_accuracy']}", flush=True)
            if best is None or va_m["joint_nll"] < best["val"]["joint_nll"]:
                best = row
        out["A2"] = {"params_note": "ствол A0 (96/24, тот же seed init_params) + xW/xU/xub, "
                                    "аддитивные головы для скоринга не используются",
                     "seconds": round(time.monotonic() - t0, 1),
                     "best_epoch": best["epoch"], "best": best, "final": hist[-1],
                     "history": hist}
        net.save_params({"trunk1": model.params["trunk1"], "b1": model.params["b1"],
                         "trunk2": model.params["trunk2"], "b2": model.params["b2"],
                         "valueW": model.params["valueW"], "valueB": model.params["valueB"],
                         "xW": model.params["xW"], "xb": model.params["xb"],
                         "xU": model.params["xU"], "xub": model.params["xub"]},
                        cfg, "pure_triple_exp",
                        paths.file_in(paths.run_dir("stage9_a2_triple"), "model_exp.json"),
                        metrics={"best": best["val"], "epoch": best["epoch"],
                                 "note": "эксперимент части C; НЕ загружается боевым конвейером"})

        # A0-референс для равнения кривых — из уже прогнанного B0 (если есть)
        if out["A0_source"]:
            b0 = json.load(open(out["A0_source"], encoding="utf-8"))["B0"]
            out["A0_reference"] = {"best_epoch": b0["best_epoch"], "best_val": b0["best"],
                                   "val_nll_curve": [h["val_joint_nll"] for h in b0["history"]],
                                   "val_decode_curve": [h["val_decode"] for h in b0["history"]],
                                   "seconds": b0["seconds"]}

        # ---------------- переобучение:train-vs-val динамика A1
        def overfit(curve):
            tr0, va0 = curve[0]["train_joint_nll"], curve[0]["val_joint_nll"]
            tr1_, va1_ = curve[-1]["train_joint_nll"], curve[-1]["val_joint_nll"]
            return {"train_delta": round(tr1_ - tr0, 4), "val_delta": round(va1_ - va0, 4),
                    "train_improved_val_not": (tr1_ < tr0) and (va1_ > min(v["val_joint_nll"]
                                                                           for v in curve) + 1e-9)}
        out["A1_overfit"] = overfit(out["A1"]["history"])
        path = os.path.join(OUT_WS, "stage9_arch_experiments.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"сохранено: {path}")
        return 0
    finally:
        paths.set_workspace(prev)


if __name__ == "__main__":
    raise SystemExit(main())
