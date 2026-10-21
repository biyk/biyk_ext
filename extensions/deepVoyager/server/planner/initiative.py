# planner/initiative.py — порядок хода и юнит симуляции (коммит №2: механика инициативы).
#
# Инициатива бросается ОДИН раз на живой токен и держится фиксированной через все раунды
# (как в dnd5e). Источник — явное поле initiative (1..30) из payload; если его нет, честный
# d20. toHit не берётся никогда: в нём смешаны точность и скорость, это не инициатива.
# Броски и разрыв ничьих идут из отдельных rng-сегментов env_seed: один seed -> один порядок,
# и ничья не разрешается алфавитом id (иначе порядок был бы структурно смещён).
import random
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

from planner.geometry import Cell


@dataclass(frozen=True)
class Unit:
    """Юнит симуляции: клетка, hp и параметры, с которыми он ходит и бьёт."""
    id: str
    cell: Cell
    hp: float
    speed_steps: int
    damage_avg: float
    reach_cells: float
    chance: float               # вероятность попадания его атаки
    hostile_to_hero: bool
    initiative: int = 0         # значение инициативы (поле или d20); 0 = не задано
    ally_to_hero: bool = False  # та же команда, что герой (ни враг, ни нейтральный)

    @property
    def is_alive(self) -> bool:
        return self.hp > 0


def roll_initiatives(candidates: Iterable[Tuple[str, int]], env_seed=None) -> Tuple[str, ...]:
    """(id, явный initiative) по живым бойцам -> порядок хода, старший инициативы первым.

    Броски идут в детерминированном обходе по id, поэтому порядок не зависит от того, в каком
    виде пришла перестановка токенов. Мёртвых в candidates быть не должно — фильтрует вызов.
    """
    dice = random.Random(f"initiative:{env_seed}")
    tie = random.Random(f"tie-break:{env_seed}")
    scored = []
    for uid, explicit in sorted(candidates):
        value = explicit if explicit > 0 else dice.randint(1, 20)
        scored.append((uid, value, tie.random()))
    scored.sort(key=lambda e: (-e[1], -e[2], e[0]))
    return tuple(uid for uid, _value, _tie in scored)


def side_of(u: Unit, hero_id: str) -> Optional[int]:
    """Команда юнита: 1 — враги, 0 — команда героя, None — нейтральные (не воюют)."""
    if u.hostile_to_hero:
        return 1
    if u.ally_to_hero or u.id == hero_id:
        return 0
    return None


def are_hostile(a: Unit, b: Unit, hero_id: str) -> bool:
    """Дерутся ли a и b: оба бойцы и по разные стороны (своему не бьём)."""
    sa, sb = side_of(a, hero_id), side_of(b, hero_id)
    return sa is not None and sb is not None and sa != sb


def allies_of(units: Dict[str, Unit]) -> Tuple[Unit, ...]:
    """Живые союзники той же команды, что герой (сам герой и нейтральные не входят)."""
    return tuple(u for u in units.values() if u.ally_to_hero and u.is_alive)


def team_actors(units: Dict[str, Unit], hero_id: str,
                order: Tuple[str, ...]) -> Tuple[str, ...]:
    """Живые бойцы команды героя (src + союзники) в порядке инициативы — кто реально ходит."""
    return tuple(uid for uid in order if side_of(units[uid], hero_id) == 0)


def living_order(units: Dict[str, Unit], order: Tuple[str, ...]) -> Tuple[str, ...]:
    """Порядок инициативы, пропущенный через живых: мёртвые выпадают из хода."""
    return tuple(uid for uid in order if units[uid].is_alive)


def next_living(units: Dict[str, Unit], order: Tuple[str, ...],
                after: Optional[str] = None) -> Optional[str]:
    """Следующий живой ходящий по инициативе (циклически); None, если живых нет."""
    living = living_order(units, order)
    if not living:
        return None
    if after is None or after not in living:
        return living[0]
    return living[(living.index(after) + 1) % len(living)]
