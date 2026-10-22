# diagnostics/stage6_bc.py — ЭТАП 6 (часть 4): короткий BC smoke-test на новой малой v3-выборке.
#
# Только проверка работоспособности пути «данные → обучение → веса», НЕ масштабное обучение:
#   • новая выходная директория (workspace=stage6_out, run=stage6_bc_smoke) — боевые runs/ не тронуты;
#   • только новая конфигурация v3 (cfg.schema=3, kind=pure — воспроизводимо на CPU, без RTX 4060);
#   • несколько эпох (хватает, чтобы проверить градиенты и снижение joint NLL);
#   • НЕ PPO, НЕ тёплый старт от старых v3-чекпойнтов (22-признаковых) — старт со случайных весов.
#
# Фиксируем РАЗДЕЛЬНО: action loss (joint NLL демонстрации) и value loss (MSE/MAE оценки),
# train/val joint NLL, долю ошибок маски (независимо-декодированное предложение вне A(s)),
# NaN/Inf в лоссах и весах, контрольные суммы весов. Отдельно проверяем, что:
#   (1) обучение меняет веса (sha случайных ≠ sha лучших);
#   (2) потеря считается по СОВМЕСТНОМУ распределению (joint NLL ≠ независимая сумма голов —
#       нормировка по A(s) активна);
#   (3) лучшая модель выбрана по validation, а не автоматически по последней эпохе.
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))     # server/
sys.path.insert(0, _HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from arent import backend, dataset, joint, net, paths, provenance, splitting, spec3, train
from stage6_common import SEED

OUT_WS = os.path.join(os.path.dirname(_HERE), "stage6_out")
DATASET_NAME = "stage6_v3"
RUN_NAME = "stage6_bc_smoke"
EPOCHS = 12


def _softmax(xs):
    top = max(xs) if xs else 0.0
    ex = [math.exp(x - top) for x in xs]
    s = sum(ex) or 1e-30
    return [e / s for e in ex]


def _loss_split(model, samples):
    """Точный разбор потери политической головы на НОВОЙ модели (без шага оптимизатора).

    action_joint_nll — тот же joint NLL, что в pure_net._accumulate: logZ по A(s) минус
    logp демонстрационной тройки. action_indep_nll — сумма независимых -logp голов БЕЗ
    совместной нормировки: если бы потеря считалась по произведению масок, эти числа совпали бы;
    их расхождение и доказывает, что нормировка идёт по совместному множеству допустимых троек.
    """
    joint_tot = indep_tot = val_se = val_ae = 0.0
    n = 0
    for s in samples:
        ip, it, iw = joint.ensure_jointly_legal(s, spec3.SCHEMA)
        legal = s["legal"]
        totals = joint.group_totals(spec3.SCHEMA)
        lp = {}
        # чистый pure-бэкенд: forward возвращает (…, logits, cache, value)
        *_, logits, _cache, value = model.forward(s)
        for group in net.GROUPS:
            allowed_i, vals = logits[group]
            probs = _softmax(vals)
            lp[group] = {i: math.log(max(p, 1e-30)) for i, p in zip(allowed_i, probs)}
        Lc, Lt, Lw = lp["cells"], lp["targets"], lp["weapons"]
        exps, top = [], float("-inf")
        for pos in range(totals["cells"]):
            for tt in range(totals["targets"]):
                for ww in range(totals["weapons"]):
                    if legal[pos][tt][ww] and pos in Lc and tt in Lt and ww in Lw:
                        u = Lc[pos] + Lt[tt] + Lw[ww]
                        exps.append(u)
                        if u > top:
                            top = u
        if not exps:
            raise RuntimeError(f"пример {joint.example_id(s)}: пустая нормировка A(s)")
        ssum = sum(math.exp(u - top) for u in exps) or 1e-30
        logZ = top + math.log(ssum)
        joint_tot += logZ - (Lc[ip] + Lt[it] + Lw[iw])
        indep_tot += -Lc[ip] + -Lt[it] + -Lw[iw]
        diff = value - float(s.get("value", 0.0))
        val_se += diff * diff
        val_ae += abs(diff)
        n += 1
    n = max(1, n)
    return {"action_joint_nll": round(joint_tot / n, 5),
            "action_indep_nll": round(indep_tot / n, 5),
            "value_mse": round(val_se / n, 6), "value_mae": round(val_ae / n, 5),
            "n": n}


def _mask_errors(model, samples):
    """Доля, где НЕЗАВИСИМОЕ декодирование голов (masked argmax по каждой) даёт тройку вне A(s).

    Именно из-за этой доли joint-BC и введён: произведение независимых masked-голов не гарантирует
    совместную легальность. Демонстрационная метка, наоборот, обязана быть в A(s) всегда (=0 вне).
    """
    illegal = 0
    for s in samples:
        *_, logits, _cache, _v = model.forward(s)
        pick = {}
        for group in net.GROUPS:
            allowed_i, vals = logits[group]
            pick[group] = allowed_i[max(range(len(vals)), key=lambda k: vals[k])] if allowed_i else -1
        key = net.y_key(spec3.SCHEMA)
        raw = {key["cells"]: pick["cells"], key["targets"]: pick["targets"],
               key["weapons"]: pick["weapons"]}
        totals = joint.group_totals(spec3.SCHEMA)
        p, t, w = raw[key["cells"]], raw[key["targets"]], raw[key["weapons"]]
        p = min(p, totals["cells"] - 1); t = min(t, totals["targets"] - 1)
        w = min(w, totals["weapons"] - 1)
        try:
            ok = bool(s["legal"][p][t][w])
        except IndexError:
            ok = False
        if not ok:
            illegal += 1
    n = max(1, len(samples))
    return {"illegal_proposals": illegal, "total": len(samples),
            "illegal_frac": round(illegal / n, 4)}


def _scan_nan(obj, path="params"):
    """Найти любой NaN/Inf в весах (рекурсивно по вложенным спискам/словарям)."""
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            bad += _scan_nan(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            bad += _scan_nan(v, f"{path}[{i}]")
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            bad.append(path)
    return bad


def main() -> int:
    prev = paths.workspace()
    paths.set_workspace(OUT_WS)
    try:
        # 1) загрузка: assert_compatible на каждой строке подтверждает НОВЫЙ формат и отбивает старый
        samples = dataset.load(DATASET_NAME)
        print(f"выборка {DATASET_NAME}: {len(samples)} примеров (все feat_version="
              f"{spec3.FEATURES_VERSION})")
        train_set, val, split_report = splitting.split_grouped(samples, frac=0.85, seed=SEED,
                                                               strict=True)
        print(f"split: train={len(train_set)} val={len(val)}, "
              f"пересечения групп={split_report['group_overlap'] or 'НЕТ'}")

        cfg = net.Config(schema=spec3.SCHEMA, kind="pure", device="cpu", epochs=EPOCHS,
                         batch=32, val_frac=0.85, seed=SEED)
        # 2) случайные веса-эталон той же cfg.seed: сравнить с обученными = «веса меняются»
        ref = backend.build(cfg, kind="pure")
        sha_init = provenance.sha256_obj(ref.params)

        # 3) короткий BC: обучаем на train, валидируем на val (наш групповой split)
        result = train.run(name=RUN_NAME, samples=train_set, val=val, cfg=cfg, epochs=EPOCHS,
                           batch=32)
        summary = result["summary"]
        history = result["history"]

        # 4) лучшая и последняя модели из чекпойнтов (net.load прогонит _check_feature_compat)
        best_path = summary["model_best"]
        last_path = summary["model"]
        best_params = net.load(best_path, expect_schema=spec3.SCHEMA)["params"]
        last_params = net.load(last_path, expect_schema=spec3.SCHEMA)["params"]
        sha_best = provenance.sha256_obj(best_params)
        sha_last = provenance.sha256_obj(last_params)
        best_model = backend.build(cfg, kind="pure", params=best_params)

        # 5) разбор потери на лучшей модели + на случайной (показать, что обучение снижает joint NLL)
        best_train = _loss_split(best_model, train_set)
        best_val = _loss_split(best_model, val)
        init_train = _loss_split(ref, train_set)
        init_val = _loss_split(ref, val)
        mask_err = _mask_errors(best_model, val)

        # 6) NaN/Inf в лоссах по эпохам и в финальных весах
        loss_nan = [f"epoch{r['epoch']}" for r in history
                    if r.get("loss") is None or (isinstance(r["loss"], float)
                                                 and (math.isnan(r["loss"])
                                                      or math.isinf(r["loss"])))]
        param_nan = _scan_nan(best_params) + _scan_nan(last_params)

        val_joint_by_epoch = [r["val"]["joint"] for r in history]
        best_epoch = summary["best_epoch"]
        best_is_last = summary["best_is_last"]
        selected_by = summary["best_metric"]
        # механизм отбора = истинный argmax по val.joint (а не «всегда последняя эпоха»):
        # лучшая эпоха обязана совпадать с индексом максимума val-кривой.
        argmax_epoch = max(range(len(val_joint_by_epoch)),
                           key=lambda i: val_joint_by_epoch[i]) + 1

        # Проверки требований части 4
        checks = {
            "weights_changed": sha_init != sha_best and sha_init != sha_last,
            "loss_over_joint": best_train["action_joint_nll"] != best_train["action_indep_nll"],
            "joint_nll_dropped": best_val["action_joint_nll"] < init_val["action_joint_nll"],
            "no_nan_inf_losses": not loss_nan,
            "no_nan_inf_params": not param_nan,
            "selected_by_validation": selected_by == "val.joint",
            "selection_is_val_argmax": best_epoch == argmax_epoch,
            "labels_all_in_As": mask_err["total"] == len(val),
            "best_epoch_le_epochs": 1 <= best_epoch <= EPOCHS,
        }

        report = {
            "config": {"schema": spec3.SCHEMA, "features_version": spec3.FEATURES_VERSION,
                       "cell_feat": spec3.dims3()["cell_feat"], "kind": "pure",
                       "epochs": EPOCHS, "batch": 32, "val_frac": 0.85, "seed": SEED,
                       "warm": None, "device": "cpu"},
            "data": {"examples": len(samples), "train": len(train_set), "val": len(val),
                      "dataset_sha256": provenance.sha256_file(dataset.samples_file(DATASET_NAME)),
                      "params_count": net.param_count(cfg)},
            "loss_split": {
                "random_model": {"train": init_train, "val": init_val},
                "best_model": {"train": best_train, "val": best_val}},
            "joint_vs_independent": {
                "note": "joint NLL нормирован по A(s); indep NLL — сумма masked-голов без "
                        "совместной нормировки; расхождение = joint-нормировка активна",
                "best_train_joint": best_train["action_joint_nll"],
                "best_train_indep": best_train["action_indep_nll"],
                "best_val_joint": best_val["action_joint_nll"],
                "best_val_indep": best_val["action_indep_nll"]},
            "mask_errors_val": mask_err,
            "nan_inf": {"losses": loss_nan, "params": param_nan},
            "weight_checksums": {"sha256_init": sha_init, "sha256_best": sha_best,
                                  "sha256_last": sha_last, "best_equals_last": sha_best == sha_last},
            "selection": {"best_metric": selected_by, "best_epoch": best_epoch,
                           "val_argmax_epoch": argmax_epoch,
                           "best_is_last": best_is_last,
                           "val_joint_by_epoch": val_joint_by_epoch,
                           "best_val_joint": summary["best"]["joint"],
                           "final_val": summary["val"]},
            "checks": checks,
        }
        out = os.path.join(OUT_WS, "stage6_bc.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)

        print(f"  случайные веса: train joint NLL={init_train['action_joint_nll']}, "
              f"val={init_val['action_joint_nll']}")
        print(f"  лучшая модель: train joint NLL={best_train['action_joint_nll']} "
              f"(indep={best_train['action_indep_nll']}), val joint NLL="
              f"{best_val['action_joint_nll']} (indep={best_val['action_indep_nll']})")
        print(f"  value: best train mse={best_train['value_mse']} mae={best_train['value_mae']}, "
              f"val mse={best_val['value_mse']} mae={best_val['value_mae']}")
        print(f"  ошибки маски (val, независимое декодирование вне A(s)): "
              f"{mask_err['illegal_proposals']}/{mask_err['total']} "
              f"({100*mask_err['illegal_frac']:.1f}%)")
        print(f"  выбор: метрика={selected_by}, best_epoch={best_epoch}/{EPOCHS}, "
              f"best_is_last={best_is_last}, val.joint по эпохам={val_joint_by_epoch}")
        print(f"  веса: init={sha_init[:12]}… best={sha_best[:12]}… last={sha_last[:12]}… "
              f"(best==last={sha_best == sha_last})")
        print(f"  NaN/Inf: losses={loss_nan or 'нет'}, params={param_nan or 'нет'}")
        print(f"  ПРОВЕРКИ: {checks}")
        ok = all(checks.values())
        print(f"  сохранено: {out}  |  SMOKE OK={ok}")
        return 0 if ok else 1
    finally:
        paths.set_workspace(prev)


if __name__ == "__main__":
    raise SystemExit(main())
