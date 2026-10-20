# arent/paths.py — все пути arent в одном месте.
#
# Папка arent переносится целиком: на машине с 4060 она лежит где угодно, а exe вообще
# запускается из dist/, где рядом с ним лежат data/ и runs/. Поэтому рабочий каталог
# определяется по месту запуска (sys.frozen -> каталог exe), а тесты и CLI могут
# переключить его целиком одной функцией (set_workspace) — иначе генерация выборки
# писалась бы в боевые данные.
import os
import sys
from typing import Any, Dict, Optional

_OVERRIDE: Optional[str] = None


def source_dir() -> str:
    """Каталог пакета arent в исходниках (там config.json и data/payloads по умолчанию)."""
    return os.path.dirname(os.path.abspath(__file__))


def _auto() -> str:
    if getattr(sys, "frozen", False):            # собранный exe: данные живут рядом с ним
        return os.path.dirname(os.path.abspath(sys.executable))
    return source_dir()


def workspace() -> str:
    return _OVERRIDE or _auto()


def set_workspace(path: Optional[str]) -> str:
    """Переключить рабочий каталог (None — обратно на автоматический)."""
    global _OVERRIDE
    _OVERRIDE = os.path.abspath(path) if path else None
    return workspace()


def data_dir() -> str:
    return os.path.join(workspace(), "data")


def payload_dir() -> str:
    """Снимки сцен: их кладёт temp/js_arena.js через CDP, обучение из них только читает.

    В собранном exe данные лежат рядом с arent.exe, но если рядом ничего не скопировали,
    подходит и вложенный в сборку комплект (_internal/arent/data/payloads).
    """
    here = os.path.join(data_dir(), "payloads")
    if os.path.isdir(here) or not getattr(sys, "frozen", False):
        return here
    return os.path.join(source_dir(), "data", "payloads")


def samples_dir() -> str:
    return os.path.join(data_dir(), "samples")


def capture_dir() -> str:
    """Снятые с /plan состояния: data/payloads/captures (их читает dataset.payload_files)."""
    return os.path.join(payload_dir(), "captures")


def runs_dir() -> str:
    """Чекпойнты обучения: runs/<имя>/model.json + history.json + summary.json."""
    return os.path.join(workspace(), "runs")


def config_file() -> str:
    """Config рядом с рабочим каталогом, а если его нет — рядом с кодом пакета."""
    here = os.path.join(workspace(), "config.json")
    return here if os.path.exists(here) else os.path.join(source_dir(), "config.json")


def run_dir(name: str) -> str:
    return ensure(os.path.join(runs_dir(), name))


def file_in(directory: str, name: str) -> str:
    return os.path.join(directory, name)


def checkpoint(name: str) -> Optional[str]:
    """runs/<имя>/model.json, если он есть: по имени прогона работают --model и --warm."""
    path = file_in(file_in(runs_dir(), name), "model.json")
    return path if os.path.exists(path) else None


def ensure(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def describe() -> Dict[str, Any]:
    return {"workspace": workspace(), "frozen": bool(getattr(sys, "frozen", False)),
            "data": data_dir(), "runs": runs_dir(), "config": config_file(),
            "payloads": os.listdir(payload_dir()) if os.path.isdir(payload_dir()) else [],
            "samples": os.listdir(samples_dir()) if os.path.isdir(samples_dir()) else [],
            "runs_listed": os.listdir(runs_dir()) if os.path.isdir(runs_dir()) else []}
