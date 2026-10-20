# planner/points_spec.py — спецификация коэффициентов: какие числа существуют,
# сколько они по умолчанию и как разбираются из points.json. Состояние загрузчика
# (путь к файлу, mtime, «пришпиленные» тестом значения) — в planner/points.py.
# Из модулей planner этот файл не знает ни о ком, кроме planner.dice — импорт только вниз.
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from planner import dice

SKIP_KEYS = ("comment", "version")     # служебные поля файла, их нет в SPEC

# Числа по умолчанию. Названы константами, чтобы значение в SPEC и значение поля
# dataclass не разъехались: Tuning(max_rounds=...) должен совпадать с SPEC.
MOVE_PER_CELL = 1.0
ATTACK_SURE = 30.0
ATTACK_DOUBT = 15.0
DAMAGE_PENALTY = -30.0
DEATH_PENALTY = -150.0
FEET_PER_CELL = 5.0
REACH_TOLERANCE = 0.5
DEFAULT_MELEE_FT = 5.0
THROWN_PROPERTY = "thr"
PLAN_TIME_LIMIT_SEC = 5.0
HIT_CHANCE = 0.65                      # вероятность попадания, если КД не прислали
UNKNOWN_DAMAGE = "1d8"                 # чем бьёт враг без поля damage
DEFAULT_SPEED_FT = 30.0                # ход токена без поля speed
DEFAULT_FEET_PER_CELL = FEET_PER_CELL
MAX_ROUNDS = 1                         # 1 = сегодняшнее одношаговое поведение
TOP_K = 8                              # вариантов первого слоя разворачивать
SHALLOW_K = 4                          # ходов героя, рассматриваемых в глубине

# Пользователь думает футами, а правила меряют клетками: cells = ft / feetPerCell.
POINT_BLANK_PATH = ("rules", "pointBlankFt")
DEFAULT_POINT_BLANK_FT = 5.0
ENEMY_REACH_PATH = ("rules", "defaultEnemyReachFt")
DEFAULT_ENEMY_REACH_FT = 5.0

#: (путь в JSON, атрибут Tuning, встроенное значение) — единственный источник чисел
SPEC: Tuple[Tuple[Tuple[str, ...], str, Any], ...] = (
    (("actions", "move", "pointsPerCell"), "move_per_cell", MOVE_PER_CELL),
    (("actions", "attack", "sure"), "attack_sure", ATTACK_SURE),
    (("actions", "attack", "doubt"), "attack_doubt", ATTACK_DOUBT),
    (("actions", "damageTaken", "points"), "damage_penalty", DAMAGE_PENALTY),
    (("actions", "damageTaken", "death"), "death_penalty", DEATH_PENALTY),
    (("rules", "feetPerCell"), "feet_per_cell", FEET_PER_CELL),
    (("rules", "reachToleranceCells"), "reach_tolerance", REACH_TOLERANCE),
    (("rules", "defaultMeleeFt"), "default_melee_ft", DEFAULT_MELEE_FT),
    (("rules", "thrownProperty"), "thrown_property", THROWN_PROPERTY),
    (("rules", "hitChance"), "hit_chance", HIT_CHANCE),
    (("rules", "unknownDamage"), "unknown_damage", UNKNOWN_DAMAGE),
    (("rules", "defaultSpeedFt"), "default_speed_ft", DEFAULT_SPEED_FT),
    (("limits", "planTimeLimitSec"), "plan_time_limit_sec", PLAN_TIME_LIMIT_SEC),
    (("lookahead", "rounds"), "max_rounds", MAX_ROUNDS),
    (("lookahead", "topK"), "top_k", TOP_K),
    (("lookahead", "shallowK"), "shallow_k", SHALLOW_K),
)

DEFAULTS: Dict[str, Any] = {".".join(path): value for path, _, value in SPEC}
DEFAULTS[".".join(POINT_BLANK_PATH)] = DEFAULT_POINT_BLANK_FT
DEFAULTS[".".join(ENEMY_REACH_PATH)] = DEFAULT_ENEMY_REACH_FT
_KNOWN = {path for path, _, _ in SPEC} | {POINT_BLANK_PATH, ENEMY_REACH_PATH}
_CONTAINERS = {path[:i] for path in _KNOWN for i in range(len(path))}


@dataclass(frozen=True)
class Tuning:
    """Действующие коэффициенты: числа из points.json, подмешанные к встроенным.

    Новые поля — со значениями по умолчанию: dataclasses.replace(...) поверх
    короткого списка полей остаётся рабочим (так делают тесты и playground).
    """
    move_per_cell: float        # очки за клетку сближения
    attack_sure: float          # очки за уверенную атаку
    attack_doubt: float         # очки за атаку с помехой
    damage_penalty: float       # штраф за сам факт полученного урона (за раунд)
    feet_per_cell: float        # футов в клетке сетки
    point_blank_cells: float    # «в упор» для дальнобойного, в клетках
    reach_tolerance: float      # допуск на диагональ и край токена, в клетках
    default_melee_ft: float     # дальность оружия, если sureFt не прислали
    thrown_property: str        # код свойства «метательное» (исключение помехи)
    plan_time_limit_sec: float  # лимит перебора вариантов хода
    death_penalty: float = DEATH_PENALTY            # штраф за «смерть» героя в симуляции
    hit_chance: float = HIT_CHANCE                  # попадание без данных по КД
    unknown_damage: str = UNKNOWN_DAMAGE            # строка кубика для врага без damage
    unknown_damage_avg: float = dice.average(UNKNOWN_DAMAGE)   # она же в очках урона
    default_speed_ft: float = DEFAULT_SPEED_FT      # ход врага без поля speed
    default_enemy_reach_cells: float = DEFAULT_ENEMY_REACH_FT / DEFAULT_FEET_PER_CELL
    max_rounds: int = MAX_ROUNDS                    # на сколько раундов смотреть вперёд
    top_k: int = TOP_K                              # кандидатов первого слоя
    shallow_k: int = SHALLOW_K                      # ходов героя в глубине


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


def _cells_from_feet(raw: Dict[str, Any], path: Tuple[str, ...], default: float,
                     notes: List[str], feet: float) -> float:
    """Футы из файла -> клетки (тот же пересчёт, что у «в упор» и досягаемости врага)."""
    found, present = _dig(raw, path)
    feet_raw = _coerce(found, default, notes, path) if present else default
    return feet_raw / feet if feet > 0 else default / FEET_PER_CELL


def _build(raw: Dict[str, Any], notes: Optional[List[str]] = None) -> Tuning:
    """Собрать Tuning из разобранного JSON (пустой dict = чистые DEFAULTS)."""
    notes = [] if notes is None else notes
    values: Dict[str, Any] = {}
    for path, attr, default in SPEC:
        found, present = _dig(raw, path)
        values[attr] = _coerce(found, default, notes, path) if present else default
    for attr in ("max_rounds", "top_k", "shallow_k"):
        values[attr] = max(1, int(round(values[attr])))   # глубина и ширина целые
    feet = values["feet_per_cell"]
    if feet <= 0:
        notes.append("rules.feetPerCell должен быть больше 0, берём 5")
        feet = values["feet_per_cell"] = FEET_PER_CELL
    values["point_blank_cells"] = _cells_from_feet(raw, POINT_BLANK_PATH,
                                                   DEFAULT_POINT_BLANK_FT, notes, feet)
    values["default_enemy_reach_cells"] = _cells_from_feet(raw, ENEMY_REACH_PATH,
                                                           DEFAULT_ENEMY_REACH_FT, notes, feet)
    average = dice.average(values["unknown_damage"])
    if average <= 0:
        notes.append(f"rules.unknownDamage: {values['unknown_damage']!r} не кубик, "
                     f"берём {UNKNOWN_DAMAGE}")
        average = dice.average(UNKNOWN_DAMAGE)
    values["unknown_damage_avg"] = average
    return Tuning(**values)


def unknown_key_notes(raw: Any, notes: List[str], path: Tuple[str, ...] = ()) -> None:
    """Заметить опечатки в ключах — иначе «поправил, а ничего не поменялось» невыловимо."""
    if not isinstance(raw, dict):
        return
    for key, value in raw.items():
        if key in SKIP_KEYS:
            continue
        here = path + (key,)
        if here in _CONTAINERS:
            unknown_key_notes(value, notes, here)
        elif here not in _KNOWN:
            notes.append(f"неизвестный ключ {'.'.join(here)} — он ни на что не влияет")


def describe(t: Tuning) -> str:
    """Компактная сводка коэффициентов для консоли сервера."""
    return (f"уверенная={t.attack_sure:g}, сомнительная={t.attack_doubt:g}, "
            f"ход={t.move_per_cell:g}/клетку, клетка={t.feet_per_cell:g}фт, "
            f"вупор={t.point_blank_cells * t.feet_per_cell:g}фт, "
            f"урон={t.damage_penalty:g}, смерть={t.death_penalty:g}, "
            f"раундов={t.max_rounds:g}, враг={t.unknown_damage_avg:g}ур, "
            f"попад={t.hit_chance:g}, лимит={t.plan_time_limit_sec:g}с")
