# planner/service.py — точка входа планировщика хода NPC.
#
# Эндпоинт /plan вызывает PlannerService.run(payload). По пункту 3 todo.md
# на данном шаге собственный расчёт вместо ответа LLM возвращает пустой массив;
# структура готова для наращивания:
#   • пункт 4 — StrategyEnumerator: перебор целей/алгоритмов сближения и атаки,
#     оценка Scorer'ом, лимит PLAN_TIME_LIMIT_SEC;
#   • пункт 5 — playground + многораундовый lookahead (см. todo.md);
#   • пункт 6 — долговременное планирование стратегий в БД.
from typing import Any, Dict, List

from planner.action import Action
from planner.context import BattleContext
from planner.scoring import Scorer


class PlannerService:
    """Разбирает запрос, строит контекст боя и возвращает план действий."""

    def __init__(self, scorer: Scorer = None):
        self.scorer = scorer or Scorer()

    def run(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """JSON-in / JSON-out форма действий. ValueError — некорректный запрос."""
        context = BattleContext.from_payload(payload)
        return [a.to_dict() for a in self.plan(context)]

    def plan(self, context: BattleContext) -> List[Action]:
        """Собственный расчёт хода. Пункт 3: всегда пустой список (заглушка)."""
        # TODO (пункт 4): candidates = StrategyEnumerator(context, PathfindingService(context)).enumerate()
        #                  return max(candidates, key=lambda c: self.scorer.score(context, c), default=[])
        return []
