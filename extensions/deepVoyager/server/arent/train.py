# arent/train.py — behavior cloning: учим три головы слотов и стоимость по разметке плана.
#
# Разметку даёт планировщик (teacher.py), поэтому модель учится повторять ровно тот
# код, что уже отвечает на /plan.
#
# ЭТАП 8: критерий отбора согласован с objective и serving. BC минимизирует joint NLL по
# A(s); serving (Этап 7) выбирает joint argmax по A(s) — значит чекпойпт меряется той же
# функцией: model_best.json = веса ЭПОХИ С МИНИМАЛЬНЫМ val.joint_nll по ВСЕЙ val-выборке
# (метрика выбора — summary["best_metric"]); val.joint_decode_accuracy — сопутствующая,
# независимая accuracy переименована в independent_baseline_accuracy и НЕ участвует в
# выборе. row["loss"] — среднее по всем батчам эпохи с весом по размеру, не «последний
# батч». При малых выборках последний прогон обычно уже переобучен, поэтому играем best.
#
# Состояние оптимизатора между запусками НЕ сохраняется: --warm возвращает прежние веса,
# но моментум (pure) и моменты Adam (torch) начинаются заново — первые эпохи после
# дообучения всегда чуть «трясутся", это ожидаемо, а не признак испорченных весов.
import copy
import os
import random
import time
from typing import Any, Callable, Dict, List, Optional

from arent import backend, dataset, manifest, net, paths, provenance, spec, spec4, spec5, splitting
from arent.scores import batches, by_source, epoch_loss, metrics

Row = Dict[str, Any]


def _pad_columns(matrix: List[List[float]], new_cols: int) -> List[List[float]]:
    """Копия матрицы с РАШИРЕНИЕМ числа колонок нулями: старые колонки — точный префикс.

    Это ядро partial-transfer: новые признаки v4 добавлены В КОНЕЦ каждого блока (хвост state,
    хвост cell/weapon-слота), поэтому вес старых колонок остаётся на своём месте, а новые
    обнуляются (нейтральный вклад) и доучиваются. Сужение невозможно (ошибка формы)."""
    if not matrix:
        return matrix
    old = len(matrix[0])
    if old == new_cols:
        return [row[:] for row in matrix]
    if old > new_cols:
        raise RuntimeError(f"partial-transfer: старых колонок {old} > новых {new_cols} — сужение невозможно")
    pad = [0.0] * (new_cols - old)
    return [row[:] + pad for row in matrix]


def _transfer_3_to_4(old_params: Dict[str, Any], old_dims: Dict[str, int],
                     new_dims: Dict[str, int], head: int) -> Dict[str, Any]:
    """Partial-transfer весов v3(или v2) -> v4: copy[:, :old] + zeros[:, old:] по хвостовым колонкам.

    Растут ТОЛЬКО: trunk1 (state -> +resource-хвост), headW["cells"] (+provokesAo/aoRisk),
    headW["weapons"] (+isAction/isBonus/isReaction). Всё остальное (b1, trunk2/b2, headB/U/UB,
    headW["targets"], valueW/valueB) побитово совпадает по форме и копируется как есть.
    Новые нулевые колонки = нейтральный вклад — стандартная инициализация приращенных фич."""
    out = copy.deepcopy(old_params)
    out["trunk1"] = _pad_columns(old_params["trunk1"], new_dims["state"])
    feat_key = {"cells": "cell_feat", "targets": "target_feat", "weapons": "weapon_feat"}
    for group, key in feat_key.items():
        out["headW"][group] = _pad_columns(old_params["headW"][group], head + new_dims[key])
    return out


def _transfer_4_to_5(old_params: Dict[str, Any], cfg5: "net.Config") -> Dict[str, Any]:
    """Partial-transfer v4 -> v5: старые веса побитово + свежая maneuver-голова (Этап 3/7).

    v5 = v4 + четвертая голова «maneuvers»; state/cell/target/weapon ширины НЕ растут
    (encode_v5: ствол и старые головы bit-for-bit v4, специфика манёвра — только в slot-векторе
    maneuvers). Поэтому перенос тривиален: deepcopy v4-весов и привить init_params(v5) ключи
    maneuvers (headW/headB/headU/headUB). манёвр-голова случайна — её и должен выучить BC/DAgger/PPO."""
    out = copy.deepcopy(old_params)
    fresh = net.init_params(cfg5)
    for key in ("headW", "headB", "headU", "headUB"):
        out[key]["maneuvers"] = fresh[key]["maneuvers"]
    return out


def _warm_params(cfg: net.Config, warm: str):
    """Весы из чекпойнта для дообучения: имя прогона в runs/ или путь к model.json.

    та же схема -> веса побитово. Чекпойнт v3(или v2) в cfg.schema=4 -> partial-transfer
    (копируем общие колонки, обнуляем хвост ресурсов/Ao-фич), если hidden/head совпадают."""
    path = warm if os.path.exists(warm) else paths.checkpoint(warm)
    if not path:
        raise RuntimeError(f"Чекпойнта нет: {warm} — имя прогона в runs/ или путь к model.json")
    checkpoint = net.load(path)
    saved = net.Config.from_dict(checkpoint.get("config") or {})
    if (saved.hidden, saved.head) != (cfg.hidden, cfg.head):
        raise RuntimeError(f"Чекпойнт {path}: hidden={saved.hidden}/head={saved.head}, "
                           f"просим {cfg.hidden}/{cfg.head} — веса другой формы")
    saved_schema = getattr(saved, "schema", 2)
    want_schema = getattr(cfg, "schema", spec.SCHEMA)
    if saved_schema == want_schema:
        return checkpoint["params"], path, None
    if want_schema == spec4.SCHEMA and saved_schema in (2, 3):
        old_dims = checkpoint.get("dims") or net.dims_for(saved_schema)
        new_dims = net.dims_for(want_schema)
        transferred = _transfer_3_to_4(checkpoint["params"], old_dims, new_dims, cfg.head)
        return transferred, path, saved_schema
    if want_schema == spec5.SCHEMA and saved_schema == spec4.SCHEMA:
        transferred = _transfer_4_to_5(checkpoint["params"], cfg)
        return transferred, path, saved_schema
    raise RuntimeError(f"Чекпойнт {path}: схема {saved_schema}, просим {want_schema} — веса другой "
                       f"схемы несовместимы (partial-transfer есть только v2/v3 -> v4 и v4 -> v5)")


def run(name: str = "latest", samples: Optional[List[Dict[str, Any]]] = None,
        dataset_name: Optional[str] = None, cfg: Optional[net.Config] = None,
        kind: Optional[str] = None, epochs: Optional[int] = None, batch: Optional[int] = None,
        lr: Optional[float] = None, hidden: Optional[int] = None, head: Optional[int] = None,
        warm: Optional[str] = None, device: Optional[str] = None,
        val: Optional[List[Dict[str, Any]]] = None, log: Optional[Callable] = None
        ) -> Dict[str, Any]:
    """Обучить и сохранить; возвращает отчёт (чекпойнты, метрики, история по эпохам).

    warm — продолжить веса чекпойнта, а не начинать со случайных (оптимизатор всё равно
    новый: моментум и состояния Adam по прежним прогонам в файл не пишутся).
    val — отдельный набор примеров для проверки (замороженные старые сценарии); без него
    валидация отщипывается от samples.
    """
    say = log or _echo
    cfg = cfg or net.default_config()
    cfg.hidden = hidden or cfg.hidden
    cfg.head = head or cfg.head
    cfg.device = device or cfg.device
    epochs = epochs or cfg.epochs
    batch = batch or cfg.batch
    params, warm_from = (None, None)
    warm_from_schema = None
    if warm:
        params, warm_from, warm_from_schema = _warm_params(cfg, warm)
        if warm_from_schema is not None:
            say(f"довыучивание от {warm_from} (partial-transfer v{warm_from_schema}->v{cfg.schema}: "
                f"общие колонки перенесены, хвост ресурсов/Ao обнулён)")
        else:
            say(f"довыучивание от {warm_from} (веса прежние, оптимизатор новый)")
    dataset_file = None
    if samples is None:
        source = dataset_name or dataset.latest_samples()
        if not source:
            raise RuntimeError("Выборки нет: сначала arent gen")
        dataset_file = dataset.samples_file(source)
        samples = dataset.load(source)
        say(f"выборка {source}: {len(samples)} примеров")
    elif dataset_name:
        dataset_file = dataset.samples_file(dataset_name)
    split_report = None
    if val is None:
        train_set, val, split_report = splitting.split_grouped(samples, cfg.val_frac, cfg.seed)
        val_source = "grouped"
    else:
        train_set = samples
        val_source = "override"
    model = backend.build(cfg, kind=kind or cfg.kind, params=params)
    if lr is None and model.name == "pure":
        lr = max(cfg.lr, 0.05)          # SGD-моментуму нужен шаг крупнее, чем Adam
    say(f"бэкенд {model.name} на {getattr(model, 'device', 'cpu')}: "
        f"{len(train_set)} train / {len(val)} val, {epochs} эпох")
    rng = random.Random(cfg.seed)
    history: List[Row] = []
    started = time.monotonic()
    # ЭТАП 8: отбор по МИНИМУМУ joint NLL — того же члена, что оптимизирует BC-шаг
    # (pure_net._accumulate / torch_net.step_batch), и по всей val-выборке (scores.metrics).
    best, best_score, best_params = None, float("inf"), None
    metric = "val.joint_nll" if val else "train.joint_nll"
    epoch_started = started
    for epoch in range(1, epochs + 1):
        order = list(train_set)
        rng.shuffle(order)
        reports: List[Row] = []
        for chunk in batches(order, batch):
            reports.append(model.step_batch(chunk, lr))
        agg = epoch_loss(reports)                       # среднее по ВСЕМ батчам, вес по размеру
        row: Row = {"epoch": epoch, "loss": agg["loss"], "n_samples": agg["n_samples"],
                    "lr": lr or cfg.lr,
                    "sec": round(time.monotonic() - epoch_started, 2),
                    "train": metrics(model, train_set),
                    "val": metrics(model, val) if val else {}}
        epoch_started = time.monotonic()
        val_metrics = row["val"] or row["train"]
        if val_metrics.get("joint_nll") is None:
            raise RuntimeError(
                f"epoch {epoch}: joint_nll не посчитан — модели/примерам не хватает "
                "head_logp или совместной маски 'legal'; по старой независимой accuracy "
                "чекпойпт больше не выбирают (ЭТАП 8), молча подменять критерий не будем")
        if val:
            row["val_by"] = {name: {"joint_nll": m["joint_nll"],
                                    "joint_decode_accuracy": m["joint_decode_accuracy"],
                                    "n": m["n"]} for name, m in by_source(model, val).items()}
        history.append(row)
        say(f"epoch {epoch}/{epochs} loss={row['loss']} ({row['sec']} с) | val: "
            f"joint_nll={val_metrics['joint_nll']} "
            f"decode_acc={val_metrics['joint_decode_accuracy']} "
            f"baseline_acc={val_metrics['independent_baseline_accuracy']} "
            f"value_mae={val_metrics['value_mae']} "
            f"cell={val_metrics['cell']} target={val_metrics['target']} "
            f"weapon={val_metrics['weapon']}")
        if val_metrics["joint_nll"] < best_score:
            best, best_score, best_params = row, val_metrics["joint_nll"], \
                copy.deepcopy(model.params)
    seconds = round(time.monotonic() - started, 2)
    result = _finish(name, model, cfg, history, best, best_params, seconds, len(samples), say,
                     warm_from, metric, val_source, split_report)
    manifest.build_and_write(name, cfg, dataset_file, split_report, val_source, warm_from,
                             result["summary"], from_schema=warm_from_schema)
    return result


def _finish(name: str, model: Any, cfg: net.Config, history: List[Row], best: Optional[Row],
            best_params: Optional[Dict[str, Any]], seconds: float, n_samples: int,
            say: Callable, warm_from: Optional[str] = None, metric: str = "val.joint_nll",
            val_source: str = "grouped", split_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Записать model.json (последняя эпоха), model_best.json (лучшая) и отчёты в runs/."""
    directory = paths.run_dir(name)
    final = history[-1]
    best = best or final
    checkpoint = net.save(model, paths.file_in(directory, "model.json"),
                          metrics={"which": "last", "epoch": final["epoch"],
                                   "train": final["train"], "val": final["val"],
                                   "epochs": len(history), "backend": model.name})
    best_path = None
    if best_params is not None:
        best_path = net.save_params(best_params, cfg, model.name,
                                    paths.file_in(directory, "model_best.json"),
                                    metrics={"which": "best", "epoch": best["epoch"],
                                             "selected_by": metric,
                                             "train": best["train"], "val": best["val"],
                                             "epochs": len(history), "backend": model.name})
    summary = {"name": name, "epochs": len(history), "backend": model.name,
               "device": str(getattr(model, "device", "cpu")), "seconds": seconds,
               "samples": n_samples, "params": net.param_count(cfg),
               "warm_from": warm_from, "val_source": val_source,
               "config": cfg.to_dict(), "train": final["train"], "val": final["val"],
               "best_epoch": best["epoch"], "best_metric": metric, "best": best["val"] or best["train"],
               "best_is_last": best["epoch"] == final["epoch"],
               "model": checkpoint, "model_best": best_path or checkpoint,
               "split": split_report, "dims": net.dims_for(getattr(cfg, "schema", spec.SCHEMA))}
    provenance.write_json(paths.file_in(directory, "history.json"), history)
    provenance.write_json(paths.file_in(directory, "summary.json"), summary)
    say(f"чекпойнты {checkpoint} (последняя эпоха) и {best_path or checkpoint} "
        f"(лучшая, epoch {best['epoch']} по {metric}) | {seconds} с")
    return {"checkpoint": checkpoint, "best_checkpoint": best_path or checkpoint,
            "history": history, "summary": summary,
            "train": final["train"], "val": final["val"]}


def _echo(*args: Any) -> None:
    print(*args, flush=True)
