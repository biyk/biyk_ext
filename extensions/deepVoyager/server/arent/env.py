# arent/env.py — RL-среда: бой как эпизод (state -> reward -> done) поверх той же Simulation.
#
# Никакой политики здесь нет: среда отдаёт наблюдение (тот же формат, что играет модель в
# evaluate.fight), принимает выбранную тройку индексов (cell/target/weapon) и считает шаг,
# награду и терминаль. Награда держится в ОДНОМ месте — shape_reward: плотная ценность
# раунда из Simulation.advance (Scorer + ответ врагов), нормированная на VALUE_SCALE, плюс
# терминальные бонусы за выживание/зачистку. Смерть уже оштрафована внутри foes_act, не
# дублируем. Среда детерминирована: Simulation считает ожиданием (без дайсов), поэтому один
# и тот же вход и та же последовательность действий дают один и тот же результат.
from typing import Any, Dict, Optional, Tuple

from arent import encode, spec
from arent import slots as slots_mod
from arent.observe import observe
from planner.context import BattleContext
from planner.sim import Simulation

Row = Dict[str, Any]


def shape_reward(value: float, done: bool, survived: bool, cleared: bool,
                 survive_bonus: float = 0.0, clear_bonus: float = 0.0) -> float:
    """Награда за шаг: ценность раунда в масштабе ~±1, бонусы — только на терминале."""
    scaled = float(value) / spec.VALUE_SCALE
    if done:
        if survived:
            scaled += survive_bonus
        if cleared:
            scaled += clear_bonus
    return round(scaled, 6)


class FightEnv:
    """Один бой = эпизод. reset -> наблюдение; step(тройка) -> (след. наблюдение|None, r, done, info)."""

    def __init__(self, rounds_cap: int = 8, survive_bonus: float = 1.0,
                 clear_bonus: float = 1.0):
        self.cap = max(1, int(rounds_cap))
        self.survive_bonus = survive_bonus
        self.clear_bonus = clear_bonus
        self.state: Optional[Simulation] = None
        self.slots: Any = None
        self.t = 0

    def reset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Новый бой из снимка сцены; возвращает первое наблюдение фиксированной схемы."""
        self.state = Simulation.of(BattleContext.from_payload(payload))
        self.t = 0
        return self._observe()

    def _observe(self) -> Dict[str, Any]:
        ctx = self.state.context_for(self.state.hero_id)
        obs = observe(ctx)
        self.slots = slots_mod.build(ctx, obs)
        return encode.observation(ctx, obs, self.slots)

    def step(self, label: Dict[str, int]) -> Tuple[Optional[Dict[str, Any]], float, bool, Row]:
        """Применить тройку индексов: decode -> advance (ход героя + ответ врагов) -> награда."""
        actions = slots_mod.decode(self.slots, dict(label))
        self.state, value = self.state.advance(actions)
        self.t += 1
        survived = not self.state.hero_dead
        cleared = not self.state.foes
        done = self.state.hero_dead or not self.state.foes or self.t >= self.cap
        reward = shape_reward(value, done, survived, cleared,
                              self.survive_bonus, self.clear_bonus)
        info = {"value": round(float(value), 4), "survived": survived, "cleared": cleared,
                "rounds": self.t, "foes_left": len(self.state.foes)}
        return ((None if done else self._observe()), reward, done, info)
