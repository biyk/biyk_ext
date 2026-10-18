# planner/points.py — коэффициенты планировщика хода: единый источник + JSON-переопределение.
#
# Тактические числа (награды, пороги дистанций, лимит перебора) заданы в SPEC ниже и
# переопределяются server/points.json: что указано — то применено, остальное из DEFAULTS.
# Файл перечитывается на ходу (mtime + размер), поэтому правку видно на следующем запросе;
# битый или отсутствующий файл не роняет запрос — держим прежние значения + строка в консоль.
# Ни от кого в planner этот модуль не зависит — импорт только в одну сторону.
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POINTS_FILE = os.path.join(SERVER_DIR, "points.json")   # переопределяется env POINTS_FILE
SKIP_KEYS = ("comment", "version")     # служебные поля файла, их нет в SPEC

# «в упор» и размер клетки пользователь задаёт футами, а правила меряют клетками:
# point_blank_cells = pointBlankFt / feetPerCell.
POINT_BLANK_PATH = ("rules", "pointBlankFt")
DEFAULT_POINT_BLANK_FT = 5.0

#: (путь в JSON, атрибут Tuning, встроенное значение) — единственный источник чисел
SPEC: Tuple[Tuple[Tuple[str, ...], str, Any], ...] = (
    (("actions", "move", "pointsPerCell"), "move_per_cell", 1.0),
    (("actions", "attack", "sure"), "attack_sure", 30.0),
    (("actions", "attack", "doubt"), "attack_doubt", 15.0),
    (("actions", "damageTaken", "points"), "damage_penalty", -30.0),
    (("rules", "feetPerCell"), "feet_per_cell", 5.0),
    (("rules", "reachToleranceCells"), "reach_tolerance", 0.5),
    (("rules", "defaultMeleeFt"), "default_melee_ft", 5.0),
    (("rules", "thrownProperty"), "thrown_property", "thr"),
    (("limits", "planTimeLimitSec"), "plan_time_limit_sec", 5.0),
)

DEFAULTS: Dict[str, Any] = {".".join(path): value for path, _, value in SPEC}
DEFAULTS[".".join(POINT_BLANK_PATH)] = DEFAULT_POINT_BLANK_FT
_KNOWN = {path for path, _, _ in SPEC} | {POINT_BLANK_PATH}
_CONTAINERS = {path[:i] for path in _KNOWN for i in range(len(path))}


@dataclass(frozen=True)
class Tuning:
    """Действующие коэффициенты: числа из points.json, подмешанные к встроенным."""
    move_per_cell: float        # очки за клетку сближения
    attack_sure: float          # очки за уверенную атаку
    attack_doubt: float         # очки за атаку с помехой
    damage_penalty: float       # штраф за полученный урон (пункт 5, пока не применяется)
    feet_per_cell: float        # футов в клетке сетки
    point_blank_cells: float    # «в упор» для дальнобойного, в клетках
    reach_tolerance: float      # допуск на диагональ и край токена, в клетках
    default_melee_ft: float     # дальность оружия, если sureFt не прислали
    thrown_property: str        # код свойства «метательное» (исключение помехи)
    plan_time_limit_sec: float  # лимит перебора вариантов хода


def default_tuning() -> Tuning:
    """Встроенные значения — те же числа, что исторически были зашиты в код."""
    return _build({})


def _dig(raw: Any, path: Tuple[str, ...]):
    """(значение по пути во вложенных dict, есть ли оно там)."""
    node = raw
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None, False
        node = node[key]
    return node, True


def _coerce(value: Any, default: Any, notes: List[str], path: Tuple[str, ...]) -> Any:
    """Значение из файла нужного типа; мусор -> встроенное значение + замечание."""
    name = ".".join(path)
    if isinstance(default, str):
        text = str(value if value is not None else "").strip()
        if not text:
            notes.append(f"{name}: пусто, берём {default!r}")
        return text or default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        notes.append(f"{name}: {value!r} не число, берём {default:g}")
        return default
    return float(value)


def _build(raw: Dict[str, Any], notes: Optional[List[str]] = None) -> Tuning:
    """Собрать Tuning из разобранного JSON (пустой dict = чистые DEFAULTS)."""
    notes = [] if notes is None else notes
    values: Dict[str, Any] = {}
    for path, attr, default in SPEC:
        found, present = _dig(raw, path)
        values[attr] = _coerce(found, default, notes, path) if present else default
    blank, present = _dig(raw, POINT_BLANK_PATH)
    blank_ft = _coerce(blank, DEFAULT_POINT_BLANK_FT, notes, POINT_BLANK_PATH) if present \
        else DEFAULT_POINT_BLANK_FT
    feet = values["feet_per_cell"]
    if feet <= 0:
        notes.append("rules.feetPerCell должен быть больше 0, берём 5")
        feet = values["feet_per_cell"] = 5.0
    values["point_blank_cells"] = blank_ft / feet
    return Tuning(**values)


def _notes_about_unknown(raw: Any, notes: List[str], path: Tuple[str, ...] = ()) -> None:
    """Заметить опечатки в ключах — иначе «поправил, а ничего не поменялось» невыловимо."""
    if not isinstance(raw, dict):
        return
    for key, value in raw.items():
        if key in SKIP_KEYS:
            continue
        here = path + (key,)
        if here in _CONTAINERS:
            _notes_about_unknown(value, notes, here)
        elif here not in _KNOWN:
            notes.append(f"неизвестный ключ {'.'.join(here)} — он ни на что не влияет")


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
    _notes_about_unknown(raw, notes)
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
    """Компактная сводка коэффициентов для консоли сервера."""
    t = t if t is not None else tuning()
    return (f"уверенная={t.attack_sure:g}, сомнительная={t.attack_doubt:g}, "
            f"ход={t.move_per_cell:g}/клетку, клетка={t.feet_per_cell:g}фт, "
            f"вупор={t.point_blank_cells * t.feet_per_cell:g}фт, "
            f"урон={t.damage_penalty:g}, лимит={t.plan_time_limit_sec:g}с")


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
