# planner/strategy.py — перебор сценариев хода (пункт 4 todo.md):
# каждая живая враждебная цель × алгоритм маршрута (direct/los) × атака в конце.
# Маршрут усекается скоростью хода; атака добавляется, только если финальная
# клетка достает цель (reach) и в запросе указан weaponId.
from dataclasses import dataclass
from typing import Iterator, List

from planner.action import Action, move_action, target_action, use_action
from planner.context import BattleContext
from planner.geometry import apply_moves, within_reach
from planner.pathfinding import PathfindingService
from planner.scoring import Scorer

# Алгоритмы прокладки маршрута (режимы libs/quin.py):
#   direct — дойти в клетку цели; los — выйти на прямую видимость цели.
PATH_MODES = ("direct", "los")


@dataclass(frozen=True)
class Candidate:
    """Один рассмотренный сценарий: куда идём, чем и сколько за это получаем."""
    kind: str          # "direct" | "los"
    target_id: str
    actions: List[Action]
    score: float = 0.0


class StrategyEnumerator:
    """Генерирует кандидаты лениво — потребитель может прерваться по лимиту времени."""

    def __init__(self, context: BattleContext, pathfinder: PathfindingService = None,
                 scorer: Scorer = None):
        self._ctx = context
        self._pathfinder = pathfinder or PathfindingService(context)
        self._scorer = scorer or Scorer()

    def enumerate(self) -> Iterator[Candidate]:
        src_id = self._ctx.src_id
        for enemy in self._ctx.hostile_targets():
            for mode in PATH_MODES:
                path = self._pathfinder.find_path(src_id, enemy.id, mode)
                path = path[: self._ctx.speed_steps]
                # Вставать на клетку существа нельзя (D&D 5e): если маршрут довёл
                # до самой клетки цели — последний шаг убираем, атака с соседней.
                if path and apply_moves(self._ctx.src_cell, path) == self._ctx.cell_of(enemy):
                    path = path[:-1]
                actions = [target_action(enemy.id)]
                actions += [move_action(d) for d in path]
                if self._can_attack(enemy, path):
                    actions.append(use_action(self._ctx.weapon_id))
                yield Candidate(
                    kind=mode, target_id=enemy.id, actions=actions,
                    score=self._scorer.score(self._ctx, actions),
                )

    def _can_attack(self, enemy, path: List[str]) -> bool:
        if not self._ctx.weapon_id:
            return False
        end = apply_moves(self._ctx.src_cell, path)
        return within_reach(end, self._ctx.cell_of(enemy), self._ctx.reach_cells)
