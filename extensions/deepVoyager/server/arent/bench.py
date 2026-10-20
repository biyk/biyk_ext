# arent/bench.py — сколько реально стоит эпоха на pure, на torch+cpu и на torch+cuda.
#
# «GPU быстрее» — предположение, а не факт: модель здесь ~50k весов, батч небольшой, а
# разметка (учитель) вообще на CPU. Поэтому замер делает один команды: `arent bench`,
# он прогоняет одинаковые данные через каждый доступный бэкенд/устройство и пишет отчёт
# в runs/bench/bench.json — его и стоит присылать с машины с 4060.
#
# Первая эпоха на CUDA всегда долгая (инициализация контекста и ядер), поэтому в отчёте
# отдельные поля: полное время и медиана эпохи.
import copy
import json
import statistics
from typing import Any, Callable, Dict, List, Optional, Tuple

from arent import backend, dataset, net, paths, train

Row = Dict[str, Any]


def candidates(kinds: Tuple[str, ...], devices: Tuple[str, ...]) -> List[Tuple[str, str]]:
    """Комбинации, которые имеет смысл мерить: у pure устройства нет, torch меряем на обоих."""
    out = []
    for kind in kinds:
        for device in devices or ("cpu",):
            if kind == "pure" and device != "cpu":
                continue
            out.append((kind, device))
    return out


def _skip_reason(kind: str, device: str) -> Optional[str]:
    if kind == "torch" and "torch" not in backend.available():
        return "torch не установлен (setup.bat или setup.bat --cpu)"
    if device == "cuda" and not backend.describe().get("cuda"):
        return "CUDA недоступна: torch собран без GPU или драйвера нет"
    return None


def run(name: str = "bench", samples: Optional[List[Dict[str, Any]]] = None,
        dataset_name: Optional[str] = None, cfg: Optional[net.Config] = None,
        epochs: Optional[int] = None, batch: Optional[int] = None,
        kinds: Tuple[str, ...] = ("pure", "torch"),
        devices: Tuple[str, ...] = ("cpu", "cuda"), log: Optional[Callable] = None) -> Dict[str, Any]:
    """Прогнать одни и те же данные через каждый доступный бэкенд; вернуть сравнение."""
    say = log or train._echo
    if samples is None:
        source = dataset_name or dataset.latest_samples()
        if not source:
            raise RuntimeError("Выборки нет: сначала arent gen")
        samples = dataset.load(source)
        say(f"выборка {source}: {len(samples)} примеров")
    base = cfg or net.default_config()
    rows: List[Row] = []
    for kind, device in candidates(kinds, devices):
        reason = _skip_reason(kind, device)
        if reason:
            say(f"{kind}/{device}: пропуск — {reason}")
            rows.append({"kind": kind, "device": device, "skipped": reason, "seconds": None})
            continue
        report = train.run(name=f"{name}_{kind}_{device}", samples=samples,
                           cfg=copy.deepcopy(base), kind=kind, device=device,
                           epochs=epochs, batch=batch, log=lambda *_a: None)
        epochs_run = report["summary"]["epochs"]
        times = [row["sec"] for row in report["history"] if row.get("sec") is not None]
        rows.append({"kind": kind, "device": device, "skipped": None,
                     "runs_on": report["summary"]["device"], "seconds": report["summary"]["seconds"],
                     "epochs": epochs_run, "first_epoch": (times or [None])[0],
                     "median_epoch": round(statistics.median(times), 2) if times else None,
                     "val": report["val"], "run": f"{name}_{kind}_{device}"})
        say(f"{kind}/{device}: {report['summary']['seconds']} с за {epochs_run} эпох, "
            f"val joint={report['val']['joint']}")
    done = sorted((row for row in rows if not row["skipped"]), key=lambda r: r["seconds"])
    table = {"samples": len(samples), "rows": rows, "fastest": done[0] if done else None}
    _write(paths.file_in(paths.run_dir(name), "bench.json"), table)
    _print(say, table)
    return table


def _print(say: Callable, table: Dict[str, Any]) -> None:
    """Отчёт в лог: чем быстрее и что именно мерялось."""
    say("замер: бэкенд/устройство -> секунды | медиана эпохи | val joint")
    for row in table["rows"]:
        if row["skipped"]:
            say(f"  {row['kind']}/{row['device']}: пропуск ({row['skipped']})")
        else:
            val = row["val"]
            say(f"  {row['kind']}/{row['device']} ({row['runs_on']}): {row['seconds']} с | "
                f"{row['median_epoch']} с | joint={val['joint']}")


def _write(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
