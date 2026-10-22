# diagnostics/stage8_smoke.py — ЭТАП 8 (части 3+5): перепроверка BC smoke на ИСПРАВЛЕННОМ отборе.
#
# Что делаем:
#   • берём СУЩЕСТВУЮЩИЙ датасет stage6_v3.jsonl (массовую генерацию не запускаем):
#     файл побайтово копируется в новый workspace stage8_out — оригиналы stage6/7 не тронуты;
#   • тот же короткий прогон: pure/CPU, 12 эпох, batch=32, val_frac=0.85, тот же фикс. seed,
#     СТАРТ ИЗ СЛУЧАЙНЫХ ВЕСОВ (тёплого старта от старых чекпойнтов нет — отбор воспроизводится
#     с нуля на новом коде метрик);
#   • по каждой эпохе — полные агрегаты train/val: joint_nll, joint_decode_accuracy,
#     independent_baseline_accuracy, value_mse/mae, number of processed examples, epoch loss;
#   • проверяем: model_best.json = argmin val.joint_nll (не последняя эпоха и НЕ argmax
#     независимой accuracy — считаем контрфактический «старый критерий»);
#   • часть 3: качество value-head лучшей эпохи на val против КОНСТАНТНОГО baseline
#     (медиана train-целеи) — baseline считается по тому же val-множеству.
import json
import os
import shutil
import statistics
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))     # server/
sys.path.insert(0, _HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from arent import backend, dataset, net, paths, provenance, scores, splitting, spec3, train
from stage6_common import SEED

SERVER = os.path.dirname(_HERE)
STAGE6_WS = os.path.join(SERVER, "stage6_out")
STAGE7_WS = os.path.join(SERVER, "stage7_out")
OUT_WS = os.path.join(SERVER, "stage8_out")
DATASET_NAME = "stage6_v3"
RUN_NAME = "stage8_bc_smoke"
EPOCHS = 12

# артефакты, которые ОБЯЗАНЫ остаться нетронутыми (сверяем sha до и после)
PROTECTED = [
    os.path.join(STAGE6_WS, "data", "samples", "stage6_v3.jsonl"),
    os.path.join(STAGE6_WS, "runs", "stage6_bc_smoke", "model.json"),
    os.path.join(STAGE6_WS, "runs", "stage6_bc_smoke", "model_best.json"),
    os.path.join(STAGE6_WS, "runs", "stage6_bc_smoke", "history.json"),
    os.path.join(STAGE6_WS, "stage6_bc.json"),
    os.path.join(STAGE7_WS, "stage7_eval.json"),
    os.path.join(STAGE7_WS, "stage7_hitrun.json"),
    os.path.join(STAGE7_WS, "stage7_value_audit.json"),
]


def _sha(p):
    return provenance.sha256_file(p)


def _median_baseline(targets, val):
    """Константный предиктор поезда (медиана/среднее) против val-целеи: MAE и MSE."""
    out = {}
    for name, const in targets:
        mae = sum(abs(const - float(s["value"])) for s in val) / len(val)
        mse = sum((const - float(s["value"])) ** 2 for s in val) / len(val)
        out[name] = {"const": round(const, 4), "val_mae": round(mae, 4),
                     "val_mse": round(mse, 6)}
    return out


def main() -> int:
    before = {p: _sha(p) for p in PROTECTED if os.path.exists(p)}

    # 1) побайтовая копия датасета в новый workspace (оригинал только читается)
    src = os.path.join(STAGE6_WS, "data", "samples", DATASET_NAME + ".jsonl")
    dst_dir = os.path.join(OUT_WS, "data", "samples")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(src))
    if not os.path.exists(dst) or _sha(src) != _sha(dst):
        shutil.copyfile(src, dst)
        for ext in (".meta.json",):
            if os.path.exists(src + ext):
                shutil.copyfile(src + ext, dst + ext)
    assert _sha(src) == _sha(dst), "копия датасета не байт-в-байт"

    prev = paths.workspace()
    paths.set_workspace(OUT_WS)
    try:
        samples = dataset.load(DATASET_NAME)
        print(f"выборка {DATASET_NAME}: {len(samples)} примеров (копия stage6, sha="
              f"{_sha(src)[:12]}…)")
        train_set, val, split_report = splitting.split_grouped(samples, frac=0.85, seed=SEED,
                                                               strict=True)
        print(f"split: train={len(train_set)} val={len(val)}, пересечения групп="
              f"{split_report['group_overlap'] or 'НЕТ'}")

        cfg = net.Config(schema=spec3.SCHEMA, kind="pure", device="cpu", epochs=EPOCHS,
                         batch=32, val_frac=0.85, seed=SEED)
        ref = backend.build(cfg, kind="pure")           # случайные веса той же cfg.seed
        init_val = scores.metrics(ref, val)             # метрики random init — точка отсчёта

        # 2) короткий BC с НОВЫМ отбором: свежий старт, 12 эпох, тот же seed
        result = train.run(name=RUN_NAME, samples=train_set, val=val, cfg=cfg, epochs=EPOCHS,
                           batch=32)
        summary, history = result["summary"], result["history"]

        # 3) таблица по эпохам (полные агрегаты, не «последний батч»)
        table = []
        for r in history:
            tr, va = r["train"], r["val"]
            table.append({"epoch": r["epoch"], "loss": r["loss"],
                          "n_samples": r["n_samples"], "sec": r.get("sec"),
                          "train": {k: tr[k] for k in ("joint_nll", "joint_decode_accuracy",
                                                       "independent_baseline_accuracy",
                                                       "value_mae", "value_mse", "n")},
                          "val": {k: va[k] for k in ("joint_nll", "joint_decode_accuracy",
                                                     "independent_baseline_accuracy",
                                                     "value_mae", "value_mse", "n")}})
        for row in table:
            print(f"  epoch {row['epoch']:>2}: loss={row['loss']} n={row['n_samples']} | "
                  f"val joint_nll={row['val']['joint_nll']:.5f} "
                  f"decode={row['val']['joint_decode_accuracy']:.3f} "
                  f"baseline={row['val']['independent_baseline_accuracy']:.3f} "
                  f"value_mae={row['val']['value_mae']:.4f}")

        # 4) отбор: argmin val.joint_nll; model_best может != последняя эпоха
        val_nll = [row["val"]["joint_nll"] for row in table]
        argmin_epoch = min(range(len(val_nll)), key=lambda i: val_nll[i]) + 1
        best_epoch = summary["best_epoch"]
        best_params = net.load(summary["model_best"], expect_schema=spec3.SCHEMA)["params"]
        last_params = net.load(summary["model"], expect_schema=spec3.SCHEMA)["params"]
        sha_best = provenance.sha256_obj(best_params)
        sha_last = provenance.sha256_obj(last_params)

        # 5) контрфакт СТАРОГО критерия: argmax независимой accuracy (бывш. val.joint)
        val_base = [row["val"]["independent_baseline_accuracy"] for row in table]
        old_epoch = max(range(len(val_base)), key=lambda i: val_base[i]) + 1
        counterfactual = {
            "old_criterion": "max val.independent_baseline_accuracy (прежнее имя «val.joint»)",
            "old_picked_epoch": old_epoch,
            "old_picked_val_joint_nll": val_nll[old_epoch - 1],
            "new_picked_epoch": best_epoch,
            "new_picked_val_joint_nll": val_nll[best_epoch - 1],
            "nll_gap_old_vs_new": round(val_nll[old_epoch - 1] - val_nll[best_epoch - 1], 5),
        }
        print(f"  отбор: best_epoch={best_epoch} (argmin={argmin_epoch}), "
              f"старый критерий выбрал бы эпоху {old_epoch} с joint_nll="
              f"{val_nll[old_epoch - 1]:.5f} (на {counterfactual['nll_gap_old_vs_new']:+.5f} хуже)")

        # 6) часть 3: value-head лучшей эпохи против константного baseline по медиане/среднему
        tr_targets = [float(s["value"]) for s in train_set]
        consts = [("median_train", statistics.median(tr_targets)),
                  ("mean_train", statistics.mean(tr_targets))]
        base_val = _median_baseline(consts, val)
        best_row = table[best_epoch - 1]["val"]
        value_quality = {
            "model_val": {"value_mae": best_row["value_mae"],
                          "value_mse": best_row["value_mse"], "n": best_row["n"],
                          "epoch": best_epoch},
            "random_init_val": {"value_mae": init_val["value_mae"],
                                "value_mse": init_val["value_mse"]},
            "const_baselines_on_val": base_val,
            "model_beats_median": best_row["value_mae"] < base_val["median_train"]["val_mae"],
            "model_beats_random": best_row["value_mae"] < init_val["value_mae"],
            "note": "value_w/архитектура не менялись; сравнение — только диагноз",
        }
        print(f"  value: model(val mae)={best_row['value_mae']:.4f} vs "
              f"median-const={base_val['median_train']['val_mae']:.4f} vs "
              f"random={init_val['value_mae']:.4f} → baseline побит="
              f"{value_quality['model_beats_median']}")

        checks = {
            "dataset_bytes_identical": _sha(src) == _sha(dst),
            "selection_metric_is_joint_nll": summary["best_metric"] == "val.joint_nll",
            "best_is_argmin_joint_nll": best_epoch == argmin_epoch,
            "all_epochs_have_joint_nll": all(v is not None for v in val_nll),
            "epoch_loss_is_full_mean": all(r["n_samples"] == len(train_set) for r in table),
            "decode_never_exceeds_1": all(0.0 <= row["val"]["joint_decode_accuracy"] <= 1.0
                                          for row in table),
            "no_nan": all(r["loss"] is not None and r["loss"] == r["loss"] for r in table),
            "artifact_differs_or_equal_documented": True,   # sha_best vs sha_last — в отчёте
            "protected_untouched": all(_sha(p) == h for p, h in before.items()
                                       if os.path.exists(p)),
        }
        report = {
            "config": {"schema": spec3.SCHEMA, "kind": "pure", "device": "cpu",
                       "epochs": EPOCHS, "batch": 32, "val_frac": 0.85, "seed": SEED,
                       "warm": None, "selection": "min val.joint_nll (ЭТАП 8)"},
            "data": {"examples": len(samples), "train": len(train_set), "val": len(val),
                     "dataset_src_sha256": _sha(src),
                     "dataset_copy_sha256": _sha(dst)},
            "per_epoch": table,
            "init_val_metrics": init_val,
            "selection": {"best_metric": summary["best_metric"], "best_epoch": best_epoch,
                          "argmin_epoch": argmin_epoch, "best_is_last": summary["best_is_last"],
                          "val_joint_nll_by_epoch": val_nll,
                          "val_decode_acc_by_epoch": [r["val"]["joint_decode_accuracy"]
                                                      for r in table],
                          "val_baseline_acc_by_epoch": val_base},
            "counterfactual_old_criterion": counterfactual,
            "value_quality": value_quality,
            "weight_checksums": {"sha256_best": sha_best, "sha256_last": sha_last,
                                 "best_equals_last": sha_best == sha_last},
            "checks": checks,
        }
        out = os.path.join(OUT_WS, "stage8_smoke.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        print(f"  веса: best={sha_best[:12]}… last={sha_last[:12]}… "
              f"(best==last={sha_best == sha_last})")
        print(f"  ПРОВЕРКИ: {checks}")
        ok = all(checks.values())
        print(f"  сохранено: {out}  |  STAGE8 SMOKE OK={ok}")
        return 0 if ok else 1
    finally:
        paths.set_workspace(prev)


if __name__ == "__main__":
    raise SystemExit(main())
