# arent/train.py — behavior cloning: учим три головы слотов и стоимость по разметке плана.
#
# Разметку даёт планировщик (teacher.py), поэтому модель учится повторять ровно тот
# код, что уже отвечает на /plan. Метрики — доля угаданных слотов по каждой голове,
# совместная доля (все три сразу: это и есть «повторить план») и MAE стоимости линии.
# Чекпойнт и история ложатся в runs/<имя>/ рядом с exe (arent/paths.py).
#
# Два чекпойнта на прогон: model.json — веса ПОСЛЕДНЕЙ эпохи, model_best.json — веса
# ЭПОХИ С ЛУЧШИМ val.joint (метрика выбора пишется в summary["best_metric"]). При малых
# выборках последний прогон обычно уже переобучен, поэтому играем best, а не last.
#
# Состояние оптимизатора между запусками НЕ сохраняется: --warm возвращает прежние веса,
# но моментум (pure) и моменты Adam (torch) начинаются заново — первые эпохи после
# дообучения всегда чуть «трясутся", это ожидаемо, а не признак испорченных весов.
import copy
import os
import random
import time
from typing import Any, Callable, Dict, List, Optional

from arent import backend, dataset, manifest, net, paths, provenance, spec, splitting
from arent.scores import batches, by_source, metrics

Row = Dict[str, Any]


def _warm_params(cfg: net.Config, warm: str):
    """Весы из чекпойнта для дообучения: имя прогона в runs/ или путь к model.json."""
    path = warm if os.path.exists(warm) else paths.checkpoint(warm)
    if not path:
        raise RuntimeError(f"Чекпойнта нет: {warm} — имя прогона в runs/ или путь к model.json")
    checkpoint = net.load(path)
    saved = net.Config.from_dict(checkpoint.get("config") or {})
    if (saved.hidden, saved.head) != (cfg.hidden, cfg.head):
        raise RuntimeError(f"Чекпойнт {path}: hidden={saved.hidden}/head={saved.head}, "
                           f"просим {cfg.hidden}/{cfg.head} — веса другой формы")
    return checkpoint["params"], path


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
    if warm:
        params, warm_from = _warm_params(cfg, warm)
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
    best, best_score, best_params = None, -1.0, None
    metric = "val.joint" if val else "train.joint"
    epoch_started = started
    for epoch in range(1, epochs + 1):
        order = list(train_set)
        rng.shuffle(order)
        report: Dict[str, Any] = {}
        for chunk in batches(order, batch):
            report = model.step_batch(chunk, lr)
        row: Row = {"epoch": epoch, "loss": report.get("loss"), "lr": lr or cfg.lr,
                    "sec": round(time.monotonic() - epoch_started, 2),
                    "train": metrics(model, train_set),
                    "val": metrics(model, val) if val else {}}
        epoch_started = time.monotonic()
        val_metrics = row["val"] or row["train"]
        if val:
            row["val_by"] = {name: {"joint": m["joint"], "n": m["n"]}
                             for name, m in by_source(model, val).items()}
        history.append(row)
        say(f"epoch {epoch}/{epochs} loss={row['loss']} ({row['sec']} с) | val: "
            f"cell={val_metrics['cell']} target={val_metrics['target']} "
            f"weapon={val_metrics['weapon']} joint={val_metrics['joint']} "
            f"value_mae={val_metrics['value_mae']}")
        if val_metrics["joint"] > best_score:
            best, best_score, best_params = row, val_metrics["joint"], copy.deepcopy(model.params)
    seconds = round(time.monotonic() - started, 2)
    result = _finish(name, model, cfg, history, best, best_params, seconds, len(samples), say,
                     warm_from, metric, val_source, split_report)
    manifest.build_and_write(name, cfg, dataset_file, split_report, val_source, warm_from,
                             result["summary"])
    return result


def _finish(name: str, model: Any, cfg: net.Config, history: List[Row], best: Optional[Row],
            best_params: Optional[Dict[str, Any]], seconds: float, n_samples: int,
            say: Callable, warm_from: Optional[str] = None, metric: str = "val.joint",
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
               "split": split_report, "dims": spec.dims()}
    provenance.write_json(paths.file_in(directory, "history.json"), history)
    provenance.write_json(paths.file_in(directory, "summary.json"), summary)
    say(f"чекпойнты {checkpoint} (последняя эпоха) и {best_path or checkpoint} "
        f"(лучшая, epoch {best['epoch']} по {metric}) | {seconds} с")
    return {"checkpoint": checkpoint, "best_checkpoint": best_path or checkpoint,
            "history": history, "summary": summary,
            "train": final["train"], "val": final["val"]}


def _echo(*args: Any) -> None:
    print(*args, flush=True)
