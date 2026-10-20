# planner/points.py — коэффициенты планировщика хода: загрузка и живая перезагрузка.
#
# Какие числа существуют и что значат — в planner/points_spec.py (Tuning/SPEC/DEFAULTS);
# здесь только состояние: откуда читать server/points.json, перечитать его, когда файл
# изменился на диске (mtime + размер), и не уронить запрос на битом JSON. Поэтому правку
# points.json видно на следующем запросе — перезапуск сервера не нужен.
# Ни от кого в planner этот модуль не зависит, кроме points_spec.
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from planner.points_spec import (DEFAULTS, SPEC, SKIP_KEYS, Tuning, _build, default_tuning,
                                 describe as _describe, unknown_key_notes)

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POINTS_FILE = os.path.join(SERVER_DIR, "points.json")   # переопределяется env POINTS_FILE

__all__ = ["SERVER_DIR", "POINTS_FILE", "Tuning", "DEFAULTS", "SPEC", "SKIP_KEYS",
           "default_tuning", "describe", "read", "resolve_path", "configure",
           "set_tuning", "tuning"]


def _load(path: str) -> Tuple[Tuning, List[str], bool]:
    """points.json -> (значения, замечания, читается ли файл). Исключений не бросает."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return default_tuning(), [f"{path} не найден — работаем по DEFAULTS"], False
    except (OSError, ValueError) as e:        # ValueError покрывает битый JSON
        return default_tuning(), [f"{path} не разобран ({e}) — значения остались прежними"], False
    if not isinstance(raw, dict):
        return default_tuning(), [f"{path}: ожидается объект с разделами actions/rules/limits"], False
    notes: List[str] = []
    tuning_obj = _build(raw, notes)
    unknown_key_notes(raw, notes)
    return tuning_obj, notes, True


def read(path: str) -> Tuple[Tuning, List[str]]:
    """Значения из файла + замечания к нему (для тестов и ручной проверки конфига)."""
    tuning_obj, notes, _ok = _load(path)
    return tuning_obj, notes


def resolve_path(path: Optional[str] = None) -> str:
    """Откуда читать points.json: аргумент > POINTS_FILE > server/points.json."""
    chosen = path or os.getenv("POINTS_FILE") or POINTS_FILE
    return chosen if os.path.isabs(chosen) else os.path.join(SERVER_DIR, chosen)


def describe(t: Optional[Tuning] = None) -> str:
    """Компактная сводка коэффициентов для консоли сервера (по умолчанию — действующих)."""
    return _describe(t if t is not None else tuning())


def _announce(notes: List[str], message: str) -> None:
    """Строка в консоль: какие коэффициенты действуют и что не так с файлом."""
    for line in [*notes, message]:
        print(f"[points] {line}", flush=True)


def _stamp(path: str):
    """(mtime, размер) файла как признак изменения; None, если файла нет."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


_STATE: Dict[str, Any] = {"path": None, "stamp": None, "tuning": None, "pinned": False}


def configure(path: Optional[str] = None) -> Tuning:
    """Явно задать файл коэффициентов (тесты, POINTS_FILE) и сразу прочитать его."""
    chosen = resolve_path(path)
    tuning_obj, notes, _ok = _load(chosen)
    _STATE.update(path=chosen, stamp=_stamp(chosen), tuning=tuning_obj, pinned=False)
    _announce(notes, f"коэффициенты из {os.path.basename(chosen)}: {describe(tuning_obj)}")
    return tuning_obj


def set_tuning(new: Optional[Tuning]) -> Optional[Tuning]:
    """Зафиксировать значения (для тестов и изоляции от чужого файла); None — снять фиксацию."""
    previous, _STATE["tuning"] = _STATE["tuning"], new
    _STATE["pinned"], _STATE["stamp"] = new is not None, None
    return previous


def tuning() -> Tuning:
    """Действующие коэффициенты; файл перечитывается, когда он изменился на диске."""
    if _STATE["tuning"] is None:
        return configure()
    if not _STATE["pinned"] and _STATE["path"] is not None:
        stamp = _stamp(_STATE["path"])
        if stamp != _STATE["stamp"]:
            fresh, notes, ok = _load(_STATE["path"])
            _STATE.update(stamp=stamp, tuning=fresh if ok else _STATE["tuning"])
            _announce(notes, f"перечитан {os.path.basename(_STATE['path'])}: "
                             f"{describe(_STATE['tuning'])}")
    return _STATE["tuning"]
