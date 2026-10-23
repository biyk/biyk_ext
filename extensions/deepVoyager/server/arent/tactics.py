# arent/tactics.py — реестр тактических тегов/штрафов и каркас shaping-сигнала.
#
# Единый источник имён (§2.3 teaching_plan): из этого модуля берут ключи §2.2 (детекторы),
# §3 (карта арен), §5 (веса в points.json) и §7 (тесты). Строка вне реестра — ошибка, а не
# «нуллевой вес»: иначе enter_reach vs avoid_reach даёт молчаливый ноль бонуса.
#
# Здесь только СЛОВАРЬ и чистые примитивы (тип шага, decay, аккумулятор focus_fire).
# Сами детекторы — в arent/tactics_detect.py, сборка шага из Simulation — в
# arent/tactics_ctx.py. Тактики считаются по ground-truth полигона (§11), НЕ по наблюдению
# модели: модель может не видеть признак, а детектор и метрика всё равно решат, был ли ход
# правомерным.
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Tag(str, Enum):
    """Положительные тактики (бонус за правомерный ход). use_high_ground — отложен (§10.4)."""
    focus_wounded = "focus_wounded"
    kill_shot = "kill_shot"
    priority_soft = "priority_soft"
    kite_max_range = "kite_max_range"
    cover_shoot = "cover_shoot"
    stand_off_shoot = "stand_off_shoot"
    break_ring = "break_ring"
    hold_choke = "hold_choke"
    avoid_reach = "avoid_reach"
    charge_from_cover = "charge_from_cover"
    anti_pincer = "anti_pincer"
    no_stack = "no_stack"
    use_high_ground = "use_high_ground"      # объявлен, отложен: высоты в движке нет
    no_idle = "no_idle"
    retreat_low_hp = "retreat_low_hp"
    focus_fire = "focus_fire"


class Penalty(str, Enum):
    """Отрицательные тактики (штраф за anti-паттерн)."""
    spread_fire = "spread_fire"
    approach_milishnik_as_archer = "approach_milishnik_as_archer"
    shoot_from_open = "shoot_from_open"
    enter_reach = "enter_reach"
    widen_contacts = "widen_contacts"
    leave_choke = "leave_choke"
    idle_turn = "idle_turn"
    melee_at_low_hp = "melee_at_low_hp"
    hit_boss_with_adds = "hit_boss_with_adds"
    stack_close = "stack_close"
    reach_penalty = "reach_penalty"


#: ключ -> «знак в реестре»: bonus даёт +, penalty даёт −. Только эти строки понимает bonus_for.
KIND: Dict[str, str] = {
    **{t.value: "bonus" for t in Tag},
    **{p.value: "penalty" for p in Penalty},
}
ALL_KEYS: Tuple[str, ...] = tuple(KIND)
BONUS_KEYS: Tuple[str, ...] = tuple(k for k, v in KIND.items() if v == "bonus")
PENALTY_KEYS: Tuple[str, ...] = tuple(k for k, v in KIND.items() if v == "penalty")

#: отложены (§10.4): объявлены, но детектор принципиально неприменим в текущем движке —
#: в гейт не входят, счётчик показывает N/A (applicable==0), а не 0%.
DEFERRED: frozenset = frozenset({"use_high_ground", "charge_from_cover"})


@dataclass(frozen=True)
class UnitView:
    """Юнит в детекторном представлении шага (§11.1 layer 2) — из Simulation/layout, не из obs."""
    id: str
    cell: Tuple[int, int]
    hp: float
    hp_max: float
    alive: bool
    reach: float = 1.0          # reach_cells (melee≈1, reach-оружие≈2)
    speed: int = 6              # speed_steps
    dmg: float = 0.0            # damage_avg
    chance: float = 0.65        # вероятность попадания его атаки
    ranged: bool = False        # is_ranged: reachFt >= 30
    role: str = "melee"         # melee/fast/reach/ranged/mobile_archer/tank
    los: bool = True            # виден ли актёру (has_los)

    @property
    def hp_frac(self) -> float:
        return self.hp / self.hp_max if self.hp_max else 0.0


@dataclass(frozen=True)
class StepCtx:
    """Всё, что нужно детекторам о ОДНОМ ходе актёра (до -> после). Чистые данные: легко
    синтезировать в unit-тестах и собирать из env (см. arent/tactics_ctx.py)."""
    actor: UnitView
    cell_after: Tuple[int, int]
    foes: Tuple[UnitView, ...] = ()          # живые враги актёра
    allies: Tuple[UnitView, ...] = ()         # живые союзники, без самого актёра
    target_id: Optional[str] = None          # выбранная цель атаки (None — нет атаки)
    attacked: bool = False
    moved: bool = False
    strike_range: float = 1.0                # досягаемость атаки актёра, в клетках
    dmg_expect: float = 0.0                  # ожидаемый урон выбранной атаки
    target_hp_before: float = 0.0            # hp цели до этого удара
    took_damage: bool = False                # актёр получил урон в этом шаге (ответ)
    cover_before: bool = False               # актёр был за укрытием до хода
    cover_after: bool = False                # актёр за укрытием после (LOS врагов перечёркнут)
    in_reach_after: bool = False             # встал в melee-зону врага после хода
    contacts_before: int = 0                 # живых врагов в melee-дистанции до
    contacts_after: int = 0                  # ... после
    at_choke_before: bool = False            # стоял в choke-клетке до хода (из layout)
    at_choke_after: bool = False             # ... после
    round_index: int = 0
    prior_allies_on_target: int = 0          # аккумулятор focus_fire: союзники уже били цель в раунде
    prior_ally_targets: Tuple[str, ...] = ()  # разные цели союзников в этом раунде


def decay_linear(iter_index: int, total_iters: int, floor: float = 0.0) -> float:
    """λ(iter) = max(floor, 1 - iter/total) (§1.3): к концу обучения shaping → 0."""
    if total_iters <= 0:
        return 1.0
    return max(float(floor), 1.0 - (iter_index / float(total_iters)))


class FocusFireAccumulator:
    """Round-аккумулятор focus_fire (§10.3): кто по какой цели уже ударил в текущем раунде.

    Сбрасывается на новом раунде; до additive текущего удара env спрашивает count_on(target)
    и choices_this_round() — по ним focus_fire/spread_fire понимают, был ли союзник раньше.
    """

    def __init__(self) -> None:
        self._by_target: Dict[str, int] = {}
        self._round: Optional[int] = None

    def observe(self, round_index: int, actor_id: str, target_id: Optional[str]) -> None:
        if self._round != round_index:          # новый раунд — аккумулятор с нуля
            self._round = round_index
            self._by_target = {}
        if target_id:
            self._by_target[target_id] = self._by_target.get(target_id, 0) + 1

    def count_on(self, target_id: Optional[str]) -> int:
        return self._by_target.get(target_id, 0) if target_id else 0

    def targets(self) -> Tuple[str, ...]:
        return tuple(self._by_target)


def detection(applicable: bool, matched: bool) -> Tuple[bool, bool]:
    """Канонический возврат детектора: (применимо ли в состоянии, совпал ли выбранный ход)."""
    return (bool(applicable), bool(matched))
