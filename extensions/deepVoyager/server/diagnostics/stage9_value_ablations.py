# diagnostics/stage9_value_ablations.py — ЭТАП 9, часть B: диагностика value-head.
#
# Один и тот же фиксированный split (stage6_v3, frac=0.85, seed=20261022, strict), одинаковые
# начальные веса (тот же cfg.seed -> net.init_params детерминирован) и seed, 12 эпох pure/CPU.
# ЯДРО (pure_net/train/scores) НЕ изменён: B2/B3 — ЭКСПЕРИМЕНТАЛЬНЫЕ ПОДКЛАССЫ здесь же,
# они никуда не переносится. Варианты:
#   B0 = текущий совместный action + value (value_w=0.5)        — воспроизводит этап 8;
#   B1 = только action-loss (value_w=0.0, weight-head не толкается);
#   B2 = только value-loss (action-градиенты в ствол/головы отключены);
#   B3 = action + value, но градиент value НЕ течёт в общий ствол (value-веть замораживает
#        ствол: обновляются только valueW/valueB; семантика действий не меняется).
# Дополнительно: косинусное сходство градиентов action- и value-задач по ОБЩЕМУ стволу
# (trunk1/b1/trunk2/b2) в двух точках: случайные веса и выученные (best B0). Отрицательный
# косинус укажет на конфликт, но сам по себе не докажет, что причина деградации в нём.
# Каждый value-предиктор сверяется с константными baseline (медиана/среднее train-целеи).
import copy
import json
import math
import os
import statistics
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
from arent import pure_net
from arent.pure_net import PurePolicy

SERVER = os.path.dirname(_HERE)
STAGE6_WS = os.path.join(SERVER, "stage6_out")
OUT_WS = os.path.join(SERVER, "stage9_out")
DATASET_NAME = "stage6_v3"
EPOCHS = 12
BATCH = 32
SEED = 20261022            # тот же, что у этапов 6/8: сопоставимость один-в-один


# ------------------------------------------------------------ экспериментальные подклассы
class NoActionPolicy(PurePolicy):
    """B2: только value-loss — совместный NLL не накапливается вовсе; ствол учится через value."""

    def _accumulate(self, sample, report):
        a1pre, a1, z2, t, _logits, _cache, value = self.forward(sample)
        p, g = self.params, self.grad
        diff = value - float(sample.get("value", 0.0))
        dv = self.cfg.value_w * diff
        report["value"] += abs(diff)
        report["loss"] += 0.5 * self.cfg.value_w * diff * diff
        vw, gv = p["valueW"], g["valueW"]
        for j in range(len(vw)):
            gv[j] += dv * t[j]
        g["valueB"] += dv
        dt = [dv * w for w in vw]                    # ствол: только value-вклад
        self._trunk_backward(sample["state"], a1pre, a1, z2, dt)


class FrozenValueTrunkPolicy(PurePolicy):
    """B3: точная копия _accumulate, но БЕЗ `dt[j] += dv*vw[j]` — value не трогает ствол.

    Градиент value идёт ТОЛЬКО в valueW/valueB (их вход t считается константой). Action-
    часть не изменена bit-for-bit (та же формула joint NLL по A(s)).
    """

    def _accumulate(self, sample, report):
        a1pre, a1, z2, t, logits, cache, value = self.forward(sample)
        p, g = self.params, self.grad
        dt = [0.0] * len(t)
        ip, it, iw = joint.ensure_jointly_legal(sample, self.cfg.schema)
        legal = sample["legal"]
        totals = joint.group_totals(self.cfg.schema)
        wanted = {"cells": ip, "targets": it, "weapons": iw}
        lp, allowed_map = {}, {}
        for group in pure_net.GROUPS:
            allowed, values = logits[group]
            probs = pure_net._softmax(values)
            lp[group] = {i: math.log(max(pr, 1e-30)) for i, pr in zip(allowed, probs)}
            allowed_map[group] = allowed
        Lc, Lt, Lw = lp["cells"], lp["targets"], lp["weapons"]
        exps, triples, top = [], [], float("-inf")
        for pos in range(totals["cells"]):
            for tt in range(totals["targets"]):
                wl = legal[pos][tt]
                for ww in range(totals["weapons"]):
                    if wl[ww] and pos in Lc and tt in Lt and ww in Lw:
                        u = Lc[pos] + Lt[tt] + Lw[ww]
                        triples.append((pos, tt, ww, u))
                        if u > top:
                            top = u
        if not triples:
            raise ValueError(f"пример {joint.example_id(sample)}: пустая нормировка A(s)")
        for pos, tt, ww, u in triples:
            exps.append(math.exp(u - top))
        ssum = sum(exps) or 1e-30
        logZ = top + math.log(ssum)
        marg = {k: {} for k in ("cells", "targets", "weapons")}
        for (pos, tt, ww, _u), e in zip(triples, exps):
            pr = e / ssum
            marg["cells"][pos] = marg["cells"].get(pos, 0.0) + pr
            marg["targets"][tt] = marg["targets"].get(tt, 0.0) + pr
            marg["weapons"][ww] = marg["weapons"].get(ww, 0.0) + pr
        report["loss"] += logZ - (Lc[ip] + Lt[it] + Lw[iw])
        for group in pure_net.GROUPS:
            report[net.y_key(self.cfg.schema)[group]] = report.get(
                net.y_key(self.cfg.schema)[group], 0.0) - lp[group][wanted[group]]
        for group in pure_net.GROUPS:
            m, wi = marg[group], wanted[group]
            for i in allowed_map[group]:
                delta = m.get(i, 0.0) - (1.0 if i == wi else 0.0)
                if delta:
                    self._slot_backward(group, cache[group][i], delta, dt)
        diff = value - float(sample.get("value", 0.0))
        dv = self.cfg.value_w * diff
        report["value"] += abs(diff)
        report["loss"] += 0.5 * self.cfg.value_w * diff * diff
        vw, gv = p["valueW"], g["valueW"]
        for j in range(len(vw)):
            gv[j] += dv * t[j]                     # valueW учится
            # НЕТ dt[j] += dv*vw[j]: ствол для value-задачи заморожен
        g["valueB"] += dv
        self._trunk_backward(sample["state"], a1pre, a1, z2, dt)


# ------------------------------------------------------------ градиенты и косинусы
def _flat_trunk_grad(model):
    v = []
    for key in ("trunk1", "b1", "trunk2", "b2"):
        g = model.grad[key]
        if isinstance(g, list) and g and isinstance(g[0], list):
            for row in g:
                v.extend(row)
        else:
            v.extend(g)
    return v


def _grad_of(model_cls, cfg, params, batch, value_w):
    """Градиент по общему стволу ОДНОЙ задачи, без шага оптимизатора (lr не вызывается)."""
    c = copy.deepcopy(cfg)
    c.value_w = value_w
    m = model_cls(c, copy.deepcopy(params))
    rep = {"loss": 0.0, "value": 0.0}
    for key in net.y_key(c.schema).values():          #PurePolicy._accumulate пишет вклады голов
        rep.setdefault(key, 0.0)
    for s in batch:
        m._accumulate(s, rep)
    return _flat_trunk_grad(m)


def _cosine(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na < 1e-12 or nb < 1e-12:
        return None, 0.0, 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb), na, nb


# ------------------------------------------------------------ прогоны вариантов
class _BuildPatch:
    """ВРЕМЕННАЯ подмена train.backend.build в этом процессе (эксперимент, ядро не тронуто)."""

    def __init__(self, cls):
        self.cls = cls
        self.orig = train.backend.build

    def __enter__(self):
        def build(cfg, kind=None, params=None):
            return self.cls(cfg, params)
        train.backend.build = build
        return self

    def __exit__(self, *a):
        train.backend.build = self.orig


def _run_variant(tag, cls, value_w, cfg_base, train_set, val, log_lines):
    cfg = copy.deepcopy(cfg_base)
    cfg.value_w = value_w
    t0 = time.monotonic()
    with _BuildPatch(cls):
        result = train.run(name=f"stage9_{tag}", samples=train_set, val=val, cfg=cfg,
                           epochs=EPOCHS, batch=BATCH,
                           log=lambda *a: log_lines.append(" ".join(str(x) for x in a)))
    return {"cfg": cfg.to_dict(), "seconds": round(time.monotonic() - t0, 1),
            "best_epoch": result["summary"]["best_epoch"],
            "best": result["summary"]["best"], "final_val": result["summary"]["val"],
            "final_train": result["summary"]["train"],
            "best_is_last": result["summary"]["best_is_last"],
            "history": [{"epoch": r["epoch"], "loss": r["loss"],
                         "val_joint_nll": r["val"]["joint_nll"],
                         "val_decode": r["val"]["joint_decode_accuracy"],
                         "val_baseline": r["val"]["independent_baseline_accuracy"],
                         "val_value_mae": r["val"]["value_mae"],
                         "val_value_mse": r["val"]["value_mse"]} for r in result["history"]],
            "model_best_path": result["summary"]["model_best"]}


def main() -> int:
    os.makedirs(OUT_WS, exist_ok=True)
    prev = paths.workspace()
    paths.set_workspace(STAGE6_WS)
    try:
        samples = dataset.load(DATASET_NAME)
    finally:
        paths.set_workspace(prev)
    paths.set_workspace(OUT_WS)                  # прогоны и чекпойнты — только в stage9_out
    try:
        train_set, val, rep = splitting.split_grouped(samples, frac=0.85, seed=SEED, strict=True)
        cfg = net.Config(schema=spec3.SCHEMA, kind="pure", device="cpu", epochs=EPOCHS,
                         batch=BATCH, val_frac=0.85, seed=SEED)
        fresh = net.init_params(cfg, net.dims_for(3))   # одинаковые старты всех вариантов
        log_lines = []
        out = {"split": {"train": len(train_set), "val": len(val),
                         "group_overlap": rep["group_overlap"],
                         "exact_state_overlap": rep["exact_state_overlap"]}}

        # ---- косинусы градиентов ДО обучения (одинаковые случайные веса)
        # аддитивность backward с ОДНИХ весов: g_action = g_full(value_w=0.5) − g_value(NoAction)
        full_g = _grad_of(PurePolicy, cfg, fresh, val, 0.5)
        value_g = _grad_of(NoActionPolicy, cfg, fresh, val, 0.5)
        # g_action = full − value (оба накоплены с ОДНИХ весов, backward аддитивен)
        act_only = [f - v for f, v in zip(full_g, value_g)]
        cos0, na0, nv0 = _cosine(act_only, value_g)
        out["grad_cosine_at_init"] = {"cos": cos0, "norm_action": round(na0, 4),
                                      "norm_value": round(nv0, 4),
                                      "note": "aditivность: g_full = g_action + g_value c одних "
                                              "весов; минус — признак конфликта задач"}

        # ---- B0..B3
        t_start = time.monotonic()
        out["B0"] = _run_variant("b0_joint", PurePolicy, 0.5, cfg, train_set, val, log_lines)
        out["B1"] = _run_variant("b1_action_only", PurePolicy, 0.0, cfg, train_set, val,
                                 log_lines)
        out["B2"] = _run_variant("b2_value_only", NoActionPolicy, 0.5, cfg, train_set, val,
                                 log_lines)
        out["B3"] = _run_variant("b3_frozen_trunk_value", FrozenValueTrunkPolicy, 0.5,
                                 cfg, train_set, val, log_lines)
        out["total_training_seconds"] = round(time.monotonic() - t_start, 1)

        # ---- косинусы на выученных весах B0 (best checkpoint)
        b0_params = net.load(out["B0"]["model_best_path"], expect_schema=3)["params"]
        full_g = _grad_of(PurePolicy, cfg, b0_params, val, 0.5)
        value_g = _grad_of(NoActionPolicy, cfg, b0_params, val, 0.5)
        act_only = [f - v for f, v in zip(full_g, value_g)]
        cos1, na1, nv1 = _cosine(act_only, value_g)
        out["grad_cosine_at_B0_best"] = {"cos": cos1, "norm_action": round(na1, 4),
                                         "norm_value": round(nv1, 4)}

        # ---- константные baseline для value на ЭТОМ же split
        tr = [float(s["value"]) for s in train_set]
        med, avg = statistics.median(tr), statistics.mean(tr)
        out["const_value_baselines_val"] = {
            "median_train": {"const": round(med, 4),
                             "mae": round(sum(abs(med - float(s["value"])) for s in val)
                                          / len(val), 4),
                             "mse": round(sum((med - float(s["value"])) ** 2 for s in val)
                                          / len(val), 6)},
            "mean_train": {"const": round(avg, 4),
                           "mae": round(sum(abs(avg - float(s["value"])) for s in val)
                                        / len(val), 4),
                           "mse": round(sum((avg - float(s["value"])) ** 2 for s in val)
                                        / len(val), 6)}}
        # value MAE random-init той же детерминированной инициализации (шкала сравнения B1)
        m0 = PurePolicy(cfg, copy.deepcopy(fresh))
        out["random_init_val"] = scores.metrics(m0, val)

        checks = {
            "split_clean": not rep["group_overlap"] and not rep["exact_state_overlap"],
            "all_variants_ran": all(k in out for k in ("B0", "B1", "B2", "B3")),
            "cosine_computed": cos0 is not None and cos1 is not None,
            "b0_reproduces_stage8_selection": out["B0"]["best_epoch"] == 8,
        }
        out["checks"] = checks
        out["log_lines"] = log_lines[-24:]
        path = os.path.join(OUT_WS, "stage9_value_ablations.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(json.dumps({k: out[k] for k in ("grad_cosine_at_init", "grad_cosine_at_B0_best",
                                              "const_value_baselines_val", "checks")},
                         ensure_ascii=False, indent=1))
        for b in ("B0", "B1", "B2", "B3"):
            r = out[b]
            print(f"{b}: best_epoch={r['best_epoch']} sec={r['seconds']} "
                  f"val nll={r['best']['joint_nll']} decode={r['best']['joint_decode_accuracy']} "
                  f"value_mae={r['best']['value_mae']} mse={r['best']['value_mse']}")
        print(f"сохранено: {path}")
        return 0 if all(checks.values()) else 1
    finally:
        paths.set_workspace(prev)


if __name__ == "__main__":
    raise SystemExit(main())
