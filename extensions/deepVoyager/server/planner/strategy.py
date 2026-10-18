# planner/strategy.py — перебор сценариев хода (пункт 4 todo.md):
# каждая живая враждебная цель × алгоритм маршрута (direct/los) × атака в конце.
# Маршрут усекается скоростью хода; атака добавляется, только если из финальной
# клетки туда достает хотя бы одно оружие (зону выбирает planner/armament.py).
from dataclasses import dataclass
from typing import Iterator, List, Optional

from planner.action import Action, move_action, target_action, use_action
from planner.armament import Weapon, best_attack
from planner.context import BattleContext
from planner.geometry import apply_moves, cell_distance
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
                strike = self._attack(enemy, path)
                if strike is not None:
                    actions.append(use_action(strike.id))
                yield Candidate(
                    kind=mode, target_id=enemy.id, actions=actions,
                    score=self._scorer.score(self._ctx, actions),
                )

    def _attack(self, enemy, path: List[str]) -> Optional[Weapon]:
        """Оружие для атаки цели из финальной клетки маршрута (None — не достать)."""
        end = apply_moves(self._ctx.src_cell, path)
        found = best_attack(self._ctx.weapons,
                            cell_distance(end, self._ctx.cell_of(enemy)))
        return found[0] if found else None
