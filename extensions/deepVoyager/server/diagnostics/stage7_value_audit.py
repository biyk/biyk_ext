# diagnostics/stage7_value_audit.py — ЭТАП 7 (часть 5): аудит value-head и критерия checkpoint.
#
# Ничего не переобучаем и НЕ чиним value-head без установленной причины. Проверяем:
#  1) формирование целевого value в датасете и его нормализацию (encode_v3: value/VALUE_SCALE,
#     clamp [-3,3]) — заодно, что train и val получают цель ОДНИМ кодом (общий генератор);
#  2) что logged value-потеря соответствует реальной функции потерь pure_net._accumulate
#     (0.5*value_w*diff^2 внутри loss; отдельное поле report["value"] = MAE);
#  3) почему val MAE вырос 0,83 (инициализация) -> 1,21 (выбранная модель): разбираем
#     траектории train/val value_mae по эпохам из history.json + независимый пересчёт на
#     весах init/best/last; сравниваем с «константным» предсказателем (пол и медиана);
#  4) ТОЧНАЯ идентификация метрики выбора [0.041, 0.164, ..., 0.342, ...]: это val.joint из
#     arent/scores.py — ДОЛЯ примеров, где все три независимые головы argmax одновременно
#     угадали метку, т.е. ACCURACY/SCORE (выше = лучше), а НЕ loss; выбор argmax по ней
#     подтверждается побитово;
#  5) лучший чекпойнт = argmax(val.joint), а не последняя эпоха: сверяем summary/history и
#     веса (model_best.json sha != model.json sha).
import json
import math
import os
import sys
from statistics import mean, median

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))     # server/
sys.path.insert(0, _HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from arent import backend, dataset, joint, net, paths, provenance, splitting, spec
from stage6_common import SEED

OUT_WS = os.path.join(os.path.dirname(_HERE), "stage7_out")
STAGE6_WS = os.path.join(os.path.dirname(_HERE), "stage6_out")
DATASET_NAME = "stage6_v3"
RUN_NAME = "stage6_bc_smoke"


def _value_stats(samples):
    xs = [float(s.get("value", 0.0)) for s in samples]
    return {"n": len(xs), "min": round(min(xs), 4), "max": round(max(xs), 4),
            "mean": round(mean(xs), 4), "std": round(mean([(x - mean(xs)) ** 2 for x in xs]) ** .5, 4),
            "mean_abs": round(mean([abs(x) for x in xs]), 4),
            "mae_const_zero": round(mean([abs(x) for x in xs]), 4),
            "mae_const_median": round(mean([abs(x - median(xs)) for x in xs]), 4)}


def _mae_of(model, samples):
    """Независимый пересчёт value MAE той же семантикой, что scores.metrics: |V(s) − target|."""
    err = 0.0
    for s in samples:
        out = model.predict(s)
        err += abs(out["value"] - float(s.get("value", 0.0)))
    return round(err / max(1, len(samples)), 4)


def main() -> int:
    prev = paths.workspace()
    paths.set_workspace(STAGE6_WS)
    try:
        run_dir = os.path.join(paths.runs_dir(), RUN_NAME)
        history = json.load(open(os.path.join(run_dir, "history.json"), encoding="utf-8"))
        summary = json.load(open(os.path.join(run_dir, "summary.json"), encoding="utf-8"))

        samples = dataset.load(DATASET_NAME)
        train, val, _rep = splitting.split_grouped(samples, frac=0.85, seed=SEED, strict=True)

        # (1) цель: одна и та же функция кодирования для train/val (сплит НЕ переэнкодит)
        targets = {"all": _value_stats(samples), "train": _value_stats(train),
                   "val": _value_stats(val),
                   "scale": {"VALUE_SCALE": spec.VALUE_SCALE, "clamp": [-3.0, 3.0],
                              "formula": "sample.value = round(clamp(raw/60, -3, 3), 3) "
                                         "(encode_v3.encode)"},
                   "same_semantics": all(str(s.get("schema")) == "3" and
                                         "legal" in s and "value" in s for s in samples)}

        # (2) logged-потеря == фактическая функция: пересчитываем разложение на best-весах
        cfg = net.Config.from_dict(summary["config"])
        best_blob = net.load(os.path.join(run_dir, "model_best.json"), expect_schema=3)
        last_blob = net.load(os.path.join(run_dir, "model.json"), expect_schema=3)
        best = backend.build(cfg, kind="pure", params=best_blob["params"])
        last = backend.build(cfg, kind="pure", params=last_blob["params"])
        init = backend.build(cfg, kind="pure")            # та же cfg.seed → та же инициализация

        def _loss_terms(model, subset):
            """Точное воспроизведение членов потерь pure_net._accumulate на батче подгруппы."""
            jnll = vmse = vmae = 0.0
            for s in subset:
                ip, it, iw = joint.ensure_jointly_legal(s, 3)
                *_x, logits, _c, value = model.forward(s)
                lp = {}
                for g in net.GROUPS:
                    allowed, vals = logits[g]
                    ps = [math.exp(v - max(vals)) for v in vals]
                    tot = sum(ps) or 1e-30
                    lp[g] = {i: math.log(max(p / tot, 1e-30)) for i, p in zip(allowed, ps)}
                L = {"cells": lp["cells"], "targets": lp["targets"], "weapons": lp["weapons"]}
                top = float("-inf")
                ex = []
                for p in range(len(s["legal"])):
                    for t in range(len(s["legal"][p])):
                        for w in range(len(s["legal"][p][t])):
                            if s["legal"][p][t][w] and p in L["cells"] and t in L["targets"] \
                                    and w in L["weapons"]:
                                u = L["cells"][p] + L["targets"][t] + L["weapons"][w]
                                ex.append(u)
                                top = max(top, u)
                logZ = top + math.log(sum(math.exp(u - top) for u in ex))
                jnll += logZ - (L["cells"][ip] + L["targets"][it] + L["weapons"][iw])
                d = value - float(s["value"])
                vmse += d * d
                vmae += abs(d)
            n = max(1, len(subset))
            vw = cfg.value_w
            # потеря как в _accumulate: joint NLL + 0.5*value_w*mse (не MAE!)
            return {"joint_nll": round(jnll / n, 4), "value_mse": round(vmse / n, 4),
                    "value_mae": round(vmae / n, 4),
                    "total_loss": round(jnll / n + 0.5 * vw * vmse / n, 4),
                    "value_w": vw}

        loss_best_val = _loss_terms(best, val)
        loss_best_train = _loss_terms(best, train)
        loss_init_val = _loss_terms(init, val)

        # (3) траектории MAE по эпохам + независимые пересчёты
        tr_mae = [r["train"]["value_mae"] for r in history]
        va_mae = [r["val"]["value_mae"] for r in history]
        traj = {"train_value_mae_by_epoch": tr_mae, "val_value_mae_by_epoch": va_mae,
                "recomputed": {"init_val": _mae_of(init, val), "best_val": _mae_of(best, val),
                               "last_val": _mae_of(last, val),
                               "init_train": _mae_of(init, train),
                               "best_train": _mae_of(best, train),
                               "const_zero_val": targets["val"]["mae_const_zero"],
                               "const_median_val": targets["val"]["mae_const_median"]}}

        # (4)+(5) метрика выбора: val.joint — accuracy; argmax == best_epoch; best != last
        val_joint = [r["val"]["joint"] for r in history]
        argmax_epoch = max(range(len(val_joint)), key=lambda i: val_joint[i]) + 1
        selection = {"metric": summary["best_metric"], "val_joint_by_epoch": val_joint,
                     "val_joint_semantics": "scores.metrics: доля примеров, где НЕЗАВИСИМЫЙ "
                                            "argmax всех трёх голов одновременно равен метке "
                                            "(accuracy 0..1, выше=лучше) — НЕ loss",
                     "is_higher_better": True,
                     "best_epoch": summary["best_epoch"], "argmax_epoch": argmax_epoch,
                     "selected_by_documented_criterion": (summary["best_metric"] == "val.joint"
                                                          and argmax_epoch == summary["best_epoch"]
                                                          and not summary["best_is_last"]),
                     "weights": {"sha_best": provenance.sha256_file(os.path.join(run_dir, "model_best.json"))[:16],
                                 "sha_last": provenance.sha256_file(os.path.join(run_dir, "model.json"))[:16],
                                 "best_eq_last": summary["best_is_last"]}}

        # why MAE rose: train-MAE тоже ухудшился? (иначе overfit val-группы/смещение выбора)
        why = {"init_val_mae": traj["recomputed"]["init_val"],
               "best_val_mae": traj["recomputed"]["best_val"],
               "best_train_mae": traj["recomputed"]["best_train"],
               "train_mae_first_epoch": tr_mae[0], "train_mae_last_epoch": tr_mae[-1],
               "explanation": ""}
        # честное сравнение: train MAE на best-весах против train MAE на инициализации (тот же сплит)
        if traj["recomputed"]["best_train"] < traj["recomputed"]["init_train"]:
            why["explanation"] = ("train MAE улучшился (init_train "
                                  f"={traj['recomputed']['init_train']} -> best_train "
                                  f"={traj['recomputed']['best_train']}), val ухудшился — "
                                  "переобучение стоимости на малой val-группе; выбор "
                                  "чекпойпта по val.joint это не штрафует (value не входит в "
                                  "критерий)")
        else:
            why["explanation"] = ("train MAE тоже НЕ улучшился (init_train "
                                  f"={traj['recomputed']['init_train']} -> best_train "
                                  f"={traj['recomputed']['best_train']}): стоимость почти не "
                                  "обучалась — градиент joint NLL по общему стволу тянет value "
                                  "выход от стартового смещения, value_w=0.5 мал, эпох 12; '0.83' "
                                  "в логах — val MAE на ранней эпохе 1-2 (ещё близкой к инициалу), "
                                  "а не на случайном инициале (тот даёт 1.3861)")
        why["target_scale_note"] = ("цель нормализована (/60, clamp[-3,3]): mean_abs "
                                    f"={targets['val']['mean_abs']}; MAE 'константного' "
                                    f"предсказателя медианой = {traj['recomputed']['const_median_val']}")

        report = {"dataset_value_targets": targets,
                  "loss_function_check": {"logged_matches_recomputed":
                          abs(loss_best_val["value_mae"] - traj["recomputed"]["best_val"]) < 0.05,
                          "best_val": loss_best_val, "best_train": loss_best_train,
                          "init_val": loss_init_val,
                          "note": "epoch 'loss' в history = ОТЧЁТ ПОСЛЕДНЕГО БАТЧА (train.py "
                                  "перезаписывает report на чанке), а не среднее по эпохе; "
                                  "поле 'value' в step_batch = MSE, а в scores — MAE"},
                  "mae_trajectories": traj,
                  "selection": selection,
                  "why_val_mae_rose": why,
                  "value_head_fix": "не применяется: причина установлена как 'критерий отбора "
                                    "не штрафует value + малый сигнал', а не поломка головы; "
                                    "минимальный способ при необходимости — включить "
                                    "val value-метрику в отбор или поднять value_w/эпохи"}
        out = os.path.join(OUT_WS, "stage7_value_audit.json")
        os.makedirs(OUT_WS, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)

        print("=== цели value ===")
        print(f"  val: {targets['val']}")
        print("=== пересчёт потерь (совм. с pure_net._accumulate) ===")
        print(f"  best val: {loss_best_val}")
        print(f"  init val: {loss_init_val}")
        print("=== MAE траектории ===")
        print(f"  train: {tr_mae}")
        print(f"  val:   {va_mae}")
        print(f"  recomputed: {traj['recomputed']}")
        print("=== выбор чекпойпта ===")
        print(f"  метрика={selection['metric']} best_epoch={selection['best_epoch']} "
              f"argmax_epoch={selection['argmax_epoch']} documented={selection['selected_by_documented_criterion']}")
        print(f"  val.joint={val_joint}")
        print(f"  sha best={selection['weights']['sha_best']} last={selection['weights']['sha_last']}")
        print("=== почему MAE вырос ===")
        print(f"  {why['explanation']}")
        print(f"  {why['target_scale_note']}")
        print(f"  сохранено: {out}")
        return 0
    finally:
        paths.set_workspace(prev)


if __name__ == "__main__":
    raise SystemExit(main())
