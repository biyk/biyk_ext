# arent/battlecast_heuristics.py — портированные тактические эвристики (чистые функции).
#
# Источник идеи: battlecast-engine (MIT), см. arent/battlecast_LICENSE.txt. Сюда
# перенесена только структура решения (выбор цели по ожидаемому урону, приоритет добить,
# оценка позиции через угрозу ответного огня), переписанная на ПРИМИТИВАХ нашей симуляции
# (planner.geometry/armament, arent.spec.hit_chance). Никаких SRD-данных не копировано.
#
# Честный список механик battlecast, которые НЕ портированы, потому что их семантики нет
# в нашей симуляции (проверено: planner не моделирует их), а не потому что лень:
#  • сопротивления/уязвимости/иммунитеты (adjustForResistance) — у токенов нет resist;
#  • состояния/кондиции (CONDITION_VALUES) — системы статусов нет;
#  • AoE-заклинания (shouldUseAoE / bestAoEPosition) — действия только move/target/use-оружие;
#  • командные тактики верхнего уровня (совместный залп по одной цели с учётом порядка
#    инициативы союзников) — одноходовой учитель оценивает EV самотеля, а не координированный
#    план всех союзников; согласование команды реализуется на полиакторном RL-уровне.
#  • выбор стратегии по модификатору INT — в payload нет интеллекта;
#
# Механики, которые РАНЬШЕ считались непортируемыми, а ТЕПЕРЬ моделируются (схема v5):
#  • провоцированные атаки (opportunity attack) и «отход без помех» (disengage) — сим
#    (planner/sim.py:_apply_opportunities) считает Ao на ШАГЕ выхода из melee-зоны врага, а
#    Отступление (манёвр) их снимает. Учитель оценивает их ЭВ-примитивами ниже
#    (avoided_opportunities/reach_contacts), согласованно с sim, а не выдуманной формулой.
#  • Уклонение (dodge) — входящие атаки по уклоняющемуся с помехой (adv=0.5 в sim);
#  • Рывок (dash) — удвоенный бюджет движения за ход (достигает клеток, недосягаемых шагом).
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from planner.armament import Weapon
from planner.geometry import Cell, cell_distance
from arent import spec

# Веса — в ЕДИНИЦАХ ожидаемого урона (обе слагаемые шкалы уже EV-урон, поэтому сравнимы).
# Provisional: точные числа валидируются сравнением учителей на этапе 3, а не taken on faith.
FINISH_VALUE = 10.0      # бонус за добивание: удар с ожиданием >= оставшегося hp цели
APPROACH_STEP = 1.0      # цена сблизиться на одну клетку, когда атаки из клетки нет
INCOMING_WEIGHT = 1.0    # ответный огонь врага считается один-в-один (та же шкала EV)
DODGE_ADV = 0.5          # множитель шанса получить удар по уклоняющемуся (ровно как в sim)

# Механики battlecast, сознательно НЕ портированные (проверено: нет в нашей симуляции).
UNSUPPORTED_MECHANICS: Tuple[str, ...] = (
    "resistance/vulnerability/immunity", "conditions", "aoe_spells",
    "pack_and_dispersion_team_tactics", "ally_affinity", "int_modifier_strategy_choice",
)


@dataclass(frozen=True)
class Enemy:
    """Враг для эвристик: клетка, живучесть, КД и EV его ответного удара (из нашего obs)."""
    id: str
    cell: Cell
    hp: float
    ac: float
    dmg_to_me: float        # chanceOnMe * dmgAvg — EV удара этого врага по нам
    reach_cells: float
    speed_cells: float


def expected_hit_damage(weapon: Weapon, enemy_ac: float, fallback: float) -> float:
    """Ожидаемый урон удара: вероятность попадания (d20 vs КД) × ожидание кубика оружия."""
    return spec.hit_chance(weapon.attack_bonus, enemy_ac, fallback) * weapon.expected_damage


def best_strike(cell: Cell, enemies: List[Enemy], weapons: List[Weapon],
                fallback: float,
                los: Optional[Callable[[Cell, Cell], bool]] = None,
                ) -> Optional[Tuple[Enemy, Weapon, float]]:
    """Лучшая атака из клетки по ожидаемому урону с приоритетом добить опасную цель.

    Легальность берём из НАШИХ зон попадания (weapon.mode_at): если ни одно оружие ни до
    кого не достает из клетки — атаки нет (None). F-D добавляет два тактических критерия:
    • линия видимости — если передан предикат los(клетка, клетка_врага), цель за стеной
      не считается атакуемой, даже когда попадает в дистанционную зону (согласовано с F-C:
      наблюдение, маски и исполнение урона сверяются с тем же правилом planner/los);
    • ценность добивания — удар, снимающий противника, приносит не только плоский бонус
      FINISH_VALUE (сокращение числа действующих врагов), но и его будущий ответный огонь
      dmg_to_me (вероятность устранить угрозу до её следующего действия).
    При равном EV фокус смещается к более опасной цели (dmg_to_me), затем к ближайшей —
    команда концентрируется на реальной угрозе, но EV остаётся первичным, поэтому цель не
    навязывается: более выгодный по уронам выстрел в другую цель всё равно победит.
    """
    best = None
    for enemy in enemies:
        if los is not None and not los(cell, enemy.cell):
            continue
        dist = cell_distance(cell, enemy.cell)
        for weapon in weapons:
            if weapon.mode_at(dist) is None:
                continue
            ev = expected_hit_damage(weapon, enemy.ac, fallback)
            if weapon.expected_damage >= enemy.hp > 0:
                # добить = убрать действующего противника И его будущий ответный огонь
                ev += FINISH_VALUE + enemy.dmg_to_me
            key = (ev, enemy.dmg_to_me, -dist)   # равный EV -> опаснее, затем ближе
            if best is None or key > best[0]:
                best = (key, enemy, weapon, ev)
    if best is None:
        return None
    return best[1], best[2], best[3]


def incoming_at_cell(cell: Cell, enemies: List[Enemy]) -> float:
    """Суммарный EV ответного огня: враги, способные добежать и ударить из этой клетки.

    О-zone = reach + speed + 1 — тот же допуск, что у observe.canReachMe и Simulation.foes_act.
    """
    return sum(e.dmg_to_me for e in enemies
               if cell_distance(cell, e.cell) <= e.reach_cells + e.speed_cells + 1)


def position_value(strike_ev: float, approach_gain: float, incoming: float) -> float:
    """Композиция оценки клетки: EV атаки (+ приоритет добить внутри strike_ev) минус угроза."""
    return strike_ev + APPROACH_STEP * approach_gain - INCOMING_WEIGHT * incoming


# ---------------------------------------------------------------------------
# Примитивы оценки МАНЁВРОВ (схема v5). Каждый — чистая функция того же состояния,
# что считает сим (planner/sim.py), поэтому serving==train: учитель размечает ровно то,
# что затем исполнит/оценит сим, а не выдуманные формулы.
def reach_contacts(cell: Cell, enemies: List[Enemy]) -> int:
    """Сколько врагов держат клетку в своей melee-зоне (dist <= reach).


    Ключ к распознаванию «окружён / выхожу из боя»: melee-зона = тот же striking_distance
    по клеткам, что в sim (_apply_opportunities was_in/now_out).
    """
    return sum(1 for e in enemies if cell_distance(cell, e.cell) <= e.reach_cells)


def avoided_opportunities(from_cell: Cell, to_cell: Cell, enemies: List[Enemy]) -> float:
    """EV ответных Ao, которых НЕ будет, если выйти from_cell->to_cell с Отступлением.

    Снимает урон тех врагов, чью melee-зону шаг покидает: был in (from_cell), стал out
    (to_cell). Ровно условие sim._apply_opportunities (was_in and now_out), агрегированное
    по всему перемещению — учитель оценивает верхнюю границу экономии без пот-шагового
    разбора маршрута (для разметки это консервативно и детерминированно).
    """
    total = 0.0
    for e in enemies:
        was_in = cell_distance(from_cell, e.cell) <= e.reach_cells
        now_out = cell_distance(to_cell, e.cell) > e.reach_cells
        if was_in and now_out:
            total += e.dmg_to_me
    return total


def movement_value(cell: Cell, me_cell: Cell, enemies: List[Enemy],
                   dodge: bool = False) -> float:
    """Оценка клетки БЕЗ удара (манёвр тратит действие): сближение минус угроза.

    approach_gain — на сколько клетка приблизилась к ближайшему к нам врагу (та же мера,
    что в BattlecastTeacher.choose для случая без strike). dodge=True halvит входящий огонь
    (Уклонение: adv=DODGE_ADV), отражая sim. Если врагов нет — только позиция (0 − 0).
    """
    if not enemies:
        return 0.0
    near = min(enemies, key=lambda e: (cell_distance(me_cell, e.cell), e.cell))
    approach = cell_distance(me_cell, near.cell) - cell_distance(cell, near.cell)
    incoming = incoming_at_cell(cell, enemies)
    if dodge:
        incoming *= DODGE_ADV
    return position_value(0.0, approach, incoming)
