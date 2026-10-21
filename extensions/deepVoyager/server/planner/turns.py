# planner/turns.py — многошаговый прогон линии боя через Simulation (метрика значения).
#
# Вынесено из sim.py, чтобы Simulation оставался про один раунд. rollout берёт план и
# добивает его жадной политикой героя ещё N раундов — одной шкалой для greedy (rounds=1)
# и lookahead: считает симуляция, а не внутренняя оценка планировщика.
from typing import List

from planner.action import Action
from planner.context import BattleContext
from planner.sim import Simulation


def rollout(context: BattleContext, actions: List[Action], rounds: int) -> float:
    """Метрика линии: план + жадная политика героя ещё N раундов — одной шкалой для
    greedy (rounds=1) и lookahead: считает симуляция, а не оценка планировщика."""
    state, total, line = Simulation.of(context), 0.0, list(actions)
    for _ in range(max(1, int(rounds))):
        state, value = state.advance(line)
        total += value
        if state.hero_dead:
            break
        options = state.hero_options()
        line = options[0] if options else []
    return total
