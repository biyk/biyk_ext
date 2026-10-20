# arent/teacher.py — учитель разметки: существующий планировщик, а не вторая модель.
#
# Разметку даёт PlannerService (тот же код, что отвечает на /plan), значение линии —
# Simulation.rollout. Глубину lookahead учителя можно понизить на время генерации
# выборки: rounds=1 — greedy за миллисекунды, rounds=3 — тот же план, что в бою,
# но секунды на каждое состояние.
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterator, List, Optional

from planner.action import Action
from planner.context import BattleContext
from planner.explore import BruteForceExplorer
from planner.points import set_tuning, tuning
from planner.scoring import Scorer
from planner.service import PlannerService, PlanResult
from planner.sim import rollout
from planner.strategy import StrategyEnumerator


@contextmanager
def pinned(rounds: Optional[int] = None, time_limit_sec: Optional[float] = None,
           shallow_k: Optional[int] = None, top_k: Optional[int] = None) -> Iterator[None]:
    """Временно зафиксировать коэффициенты планировщика и вернуть их назад.

    Нужно, чтобы выборка была воспроизводимой: points.json может лежать любой,
    а разметка учителя должна зависеть от аргументов генерации, а не от файла на диске.
    shallow_k/top_k дополнительно урезают ширину симуляции: hero_options() с 48 ходами
    на каждый раунд — это секунды на состояние, с 4 — десятки миллисекунд.
    """
    previous = tuning()
    values = replace(previous, max_rounds=max(1, rounds or 1),
                     plan_time_limit_sec=(previous.plan_time_limit_sec
                                          if time_limit_sec is None else time_limit_sec),
                     shallow_k=max(1, shallow_k) if shallow_k else previous.shallow_k,
                     top_k=max(1, top_k) if top_k else previous.top_k)
    set_tuning(values)
    try:
        yield
    finally:
        set_tuning(previous)


@dataclass
class Labeled:
    """Размеченное состояние: контекст, план учителя и его значение (шкала очков планировщика)."""
    ctx: BattleContext
    actions: List[Action]
    value: float
    score: float
    depth: int


class Teacher:
    """Планировщик в режиме учителя.

    rounds=1 — детерминированный перебор (quin-маршруты + все достижимые клетки) без
    случайных прогулок и без дедлайна: разметка воспроизводима и считается за миллисекунды.
    rounds>1 — тот же PlannerService, что отвечает на /plan, с lookahead: медленнее в
    сотни раз, но это ровно боковое поведение, поэтому его включают осознанно.
    """

    def __init__(self, rounds: int = 1, time_limit_sec: Optional[float] = None,
                 value_rounds: Optional[int] = None):
        self.rounds = max(1, int(rounds))
        self.time_limit_sec = time_limit_sec
        self.value_rounds = max(1, int(value_rounds if value_rounds is not None else rounds))

    def _greedy_best(self, ctx: BattleContext) -> Optional[PlanResult]:
        """Лучший кандидат перебора: цель × маршрут + все достижимые клетки."""
        scorer = Scorer()
        best = None
        for candidate in list(StrategyEnumerator(ctx, scorer=scorer).enumerate()) \
                + list(BruteForceExplorer(ctx, scorer=scorer).enumerate()):
            if best is None or candidate.score > best.score:
                best = candidate
        if best is None:
            return None
        return PlanResult(actions=best.actions, score=best.score, value=best.score,
                          considered=1, details="teacher=greedy")

    def label(self, payload: Dict[str, Any]) -> Labeled:
        """payload -> состояние + лучший план учителя + значение его линии (rollout)."""
        ctx = BattleContext.from_payload(payload)
        if self.rounds > 1:
            result = PlannerService(time_limit_sec=self.time_limit_sec).plan_result(ctx)
        else:
            result = self._greedy_best(ctx) or PlanResult()
        value = result.value if result.depth > 1 else rollout(ctx, result.actions, self.value_rounds)
        return Labeled(ctx=ctx, actions=result.actions, value=value,
                       score=result.score, depth=result.depth)
