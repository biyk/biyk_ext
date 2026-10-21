# arent/scenario_units.py — реестр ролей/архетипов/арсеналов и разбор состава.
#
# Только «из чего состоит бой»: общий пул ролей (герой/союзники/враги — одна таблица),
# тактические архетипы (рисунок построения + каноническая сторона deployment), вооружение
# и распределение размеров команд. Геометрия поля/стен/расстановки — в scenario_layout.py,
# сборка payload — в scenarios.py.
import copy
import random
from typing import Any, Dict, Sequence, Tuple

# Потолок состава: K_TARGETS=8 / K_ALLIES=6 в наблюдении это выдерживают без роста сети.
MAX_TEAM = 6

# Общий пул ролей: (hp-диапазон, скорость ft, damage-строки, reachFt, hitChance-диапазон).
UNIT_CLASSES: Dict[str, Dict[str, Any]] = {
    "melee":        {"hp": (6, 14),  "speed": (15, 30), "dmg": ["1d4", "1d6", "1d8"],       "reach": 5,  "hc": (0.45, 0.65)},
    "fast":         {"hp": (6, 12),  "speed": (30, 40), "dmg": ["1d6", "1d6+2"],            "reach": 5,  "hc": (0.5, 0.7)},
    "reach":        {"hp": (10, 18), "speed": (15, 30), "dmg": ["1d8", "1d8+2"],             "reach": 10, "hc": (0.45, 0.6)},
    "ranged":       {"hp": (7, 14),  "speed": (15, 30), "dmg": ["1d6+2", "1d8+2", "1d6+3"],  "reach": 30, "hc": (0.5, 0.65)},
    "mobile_archer": {"hp": (7, 12), "speed": (30, 40), "dmg": ["1d6+2", "1d8"],             "reach": 60, "hc": (0.5, 0.65)},
    "tank":         {"hp": (24, 45), "speed": (15, 20), "dmg": ["2d6+2", "2d6+3", "1d12+3"], "reach": 5,  "hc": (0.4, 0.6)},
}
CLASS_NAMES: Sequence[str] = tuple(sorted(UNIT_CLASSES))

# архетип -> построение врагов + каноническая deployment-сторона (для structured-режима).
ARCHETYPES: Dict[str, Dict[str, Any]] = {
    "duel":       {"formation": "cross",  "classes": ["melee", "fast", "reach"],  "deploy": "edge"},
    "pair":       {"formation": "line",   "classes": ["melee", "fast", "reach"],  "deploy": "edge"},
    "ring":       {"formation": "ring",   "classes": ["melee", "fast"],           "deploy": "corner"},
    "pincer":     {"formation": "pincer", "classes": ["melee", "fast", "reach"],  "deploy": "edge"},
    "line":       {"formation": "line",   "classes": ["ranged", "mobile_archer"], "deploy": "edge"},
    "chokepoint": {"formation": "cross",  "classes": ["melee", "reach", "tank"],  "deploy": "corner"},
    "cover":      {"formation": "diag",   "classes": ["ranged", "melee"],         "deploy": "diagonal"},
    "boss_adds":  {"formation": "ring",   "classes": ["tank", "melee", "fast"],   "deploy": "edge"},
    "skirmish":   {"formation": "diag",   "classes": ["ranged", "melee", "fast"], "deploy": "diagonal"},
}

# Тактические архетипы: стартовая геометрия каноническая (без джиттера) — чтобы честный
# A/B «политика против учителя» шёл на стабильной задаче, а не на шуме расстановки.
TACTICAL = frozenset({"chokepoint", "pincer", "boss_adds", "cover", "ring"})

# Вооружение: имя -> entries формата arena (id,name,damage,attackBonus,sureFt,doubtFt).
HERO_ARSENALS: Dict[str, Sequence[Dict[str, Any]]] = {
    "sword":       [{"id": "sword", "name": "Меч", "damage": "1d6+2", "attackBonus": 3, "sureFt": 5, "doubtFt": 5}],
    "greatsword":  [{"id": "gsword", "name": "Двуручный", "damage": "2d6+3", "attackBonus": 3, "sureFt": 5, "doubtFt": 5}],
    "two_melee":   [{"id": "sword", "name": "Меч", "damage": "1d6+2", "attackBonus": 3, "sureFt": 5, "doubtFt": 5},
                    {"id": "axe", "name": "Боевой топор", "damage": "1d8+2", "attackBonus": 3, "sureFt": 5, "doubtFt": 5}],
    "bow":         [{"id": "bow", "name": "Длинный лук", "damage": "1d8+2", "attackBonus": 4, "sureFt": 30, "doubtFt": 120}],
    "mixed":       [{"id": "sword", "name": "Меч", "damage": "1d6+2", "attackBonus": 3, "sureFt": 5, "doubtFt": 5},
                    {"id": "shortbow", "name": "Короткий лук", "damage": "1d6+2", "attackBonus": 3, "sureFt": 30, "doubtFt": 60}],
    "javelins":    [{"id": "jav", "name": "Дротики", "damage": "1d6", "attackBonus": 3, "sureFt": 30, "doubtFt": 60}],
}
ARSENAL_NAMES: Sequence[str] = tuple(sorted(HERO_ARSENALS))


def team_sizes(rng: random.Random) -> Tuple[int, int]:
    """(n_ours, n_foes) 1..6: duel 5%, зеркало 2-3 30%, асимметрия ±1-2 45%, 6v6 20%."""
    roll = rng.random()
    if roll < 0.05:
        return 1, 1
    if roll < 0.35:
        n = rng.randint(2, 3)
        return n, n
    if roll < 0.80:
        ours = rng.randint(1, MAX_TEAM)
        foes = min(MAX_TEAM, max(1, ours + rng.choice([-2, -1, 1, 2])))
        if foes == ours:
            foes = ours + 1 if ours < MAX_TEAM else ours - 1
        return ours, foes
    return MAX_TEAM, MAX_TEAM


def mirror_size(rng: random.Random) -> int:
    """Зеркальный состав n на n (WP1 «универсального солдата»): тот же разрез размеров,
    что у team_sizes, но без асимметричной ветки: duel 5%, 2-3 30%, любой 1..6 45%, 6v6 20%."""
    roll = rng.random()
    if roll < 0.05:
        return 1
    if roll < 0.35:
        return rng.randint(2, 3)
    if roll < 0.80:
        return rng.randint(1, MAX_TEAM)
    return MAX_TEAM


def make_unit(cls: str, rng: random.Random, num: int, disposition: int, prefix: str,
              arsenal: str | None = None) -> Dict[str, Any]:
    """Юнит роли cls из общего пула: hp/speed/damage/reach/hitChance + ЯВНАЯ инициатива
    (1..30, как в ho2_*) и свой арсенал из общего пула HERO_ARSENALS (WP1 симметрии:
    «универсальный солдат» ходит от лица любого токена, и у каждого своё оружие)."""
    spec = UNIT_CLASSES[cls]
    unit = {
        "id": f"{prefix}{num}", "name": f"{cls}-{num}", "disposition": disposition,
        "_class": cls, "hp": rng.randint(*spec["hp"]),
        "speed": rng.choice(range(spec["speed"][0], spec["speed"][1] + 1, 5)),
        "damage": rng.choice(spec["dmg"]), "reachFt": spec["reach"],
        "hitChance": round(rng.uniform(*spec["hc"]), 2),
        "initiative": rng.randint(1, 30),
    }
    if arsenal is not None:
        unit["arsenal"] = arsenal
        unit["weapons"] = copy.deepcopy(HERO_ARSENALS[arsenal])
    return unit


def stats(unit: Dict[str, Any]) -> Dict[str, Any]:
    return {k: unit[k] for k in ("hp", "speed", "damage", "reachFt", "hitChance")}
