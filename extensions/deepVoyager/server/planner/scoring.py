# planner/scoring.py — система очков стратегий (заготовки пункта 4 todo.md).
#
# Пункт 4: сближение — 1 очко за каждые 5 футов; атака — 30 очков;
# пункт 5: штраф −30 за полученный урон, многораундовый lookahead.
# Здесь — только константы и интерфейс: реализация появляется вместе
# с перебором стратегий в пункте 4 и покрывается тестами там же.
from typing import List

from planner.action import Action
from planner.context import BattleContext

# 5 футов = одна клетка сетки (gridSize px)
FEET_PER_CELL = 5
MOVE_POINT_PER_CELL = 1      # очко за каждое сближение на клетку
ATTACK_POINT = 30            # очко за каждую атаку
DAMAGE_PENALTY = -30         # штраф за получение урона (пункт 5)
PLAN_TIME_LIMIT_SEC = 5.0    # лимит времени на расчёт (пункт 4)


class Scorer:
    """Суммарные очки последовательности действий. Пустой план = 0."""

    def score(self, context: BattleContext, actions: List[Action]) -> float:
        # Пункт 4: перебор целей и алгоритмов сближения/атаки,
        # здесь считается пока только «пустой» базовый случай.
        return 0.0
