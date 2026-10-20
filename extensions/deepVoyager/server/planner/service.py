# planner/service.py — точка входа планировщика.
#
# Пункт 4 + перебор хода: три источника кандидатов (quin-маршруты ->
# полный BFS-перебор достижимых клеток -> случайные прогулки), выбор плана
# с максимумом очков; при достижении лимита времени (limits.planTimeLimitSec
# из points.json) берётся лучший из уже рассмотренных. Пункт 5: поверх этого
# перебора — многошаговый lookahead (planner/lookahead.py), лучший greedy остаётся
# фолбэком. Пункт 6 — долгосрочное планирование, пункт 7 — баффы/долечку.
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from planner.action import Action
from planner.context import BattleContext
from planner.explore import BruteForceExplorer, RandomExplorer
from planner.lookahead import SCREEN_MAX_SEC, SCREEN_SHARE, FirstLayer, Lookahead
from planner.points import tuning
from planner.scoring import Scorer
from planner.strategy import Candidate, StrategyEnumerator


@dataclass(frozen=True)
class PlanResult:
    """Лучший сценарий + диагностика для консоли сервера.

    score      — заработанные очки выбранного плана (сближение + атака);
    value      — то же, что мерит симуляция для всей линии (rounds=1 — те же очки);
    considered — сколько кандидатов успели просчитать (до дедлайна);
    depth/nodes/report — диагностика глубины: сколько раундов раскрыто и что дал lookahead;
    details    — мини-отчёт «за что очки» (дистанция до/после, число атак).
    """
    actions: List[Action] = field(default_factory=list)
    score: float = 0.0
    value: float = 0.0          # значение линии (в flat-режиме равно score)
    considered: int = 0
    depth: int = 1              # на сколько раундов посчитан план
    nodes: int = 0              # узлов симуляции раскрыто
    report: str = ""            # «R1 +31/-0 → R2 +1/-0 = 32»
    details: str = ""

    @property
    def action_dicts(self) -> List[Dict[str, Any]]:
        return [a.to_dict() for a in self.actions]


class PlannerService:
    """Сопоставляет входящий payload с последовательностью действий NPC."""

    def __init__(self, scorer: Optional[Scorer] = None,
                 time_limit_sec: Optional[float] = None,
                 rng: Optional[random.Random] = None):
        self.scorer = scorer or Scorer()
        # None — лимит из points.json; 0.0 остаётся явным (так тестируют дедлайн)
        self._time_limit_sec = (tuning().plan_time_limit_sec
                                if time_limit_sec is None else time_limit_sec)
        self._rng = rng or random.Random()

    def run(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Сырой JSON запроса -> сериализуемые действия (или ValueError при некорректном входе)."""
        return self.run_result(payload).action_dicts

    def run_result(self, payload: Dict[str, Any]) -> PlanResult:
        """То же, что run(), но с диагностикой (очки/перебор) для логирования."""
        return self.plan_result(BattleContext.from_payload(payload))

    def plan(self, context: BattleContext) -> List[Action]:
        """Лучший из рассмотренных сценариев; пустой список, если играть нечего."""
        return self.plan_result(context).actions

    def _candidates(self, context: BattleContext) -> Iterator[Candidate]:
        """Источники по приоритету: quin -> полный перебор -> рандом.

        Порядок важен при равных очках: замена только при score > best, поэтому
        победитель фиксируется первым из достигших оптимума (рандом его не
        переопределит — случайная прогулка заканчивается в достижимой клетке).
        """
        yield from StrategyEnumerator(context, scorer=self.scorer).enumerate()
        yield from BruteForceExplorer(context, scorer=self.scorer).enumerate()
        yield from RandomExplorer(context, scorer=self.scorer, rng=self._rng).enumerate()

    def plan_result(self, context: BattleContext) -> PlanResult:
        """Перебор кандидатов -> лучший greedy; если lookahead включён — ещё и глубина."""
        t = tuning()
        deep = t.max_rounds > 1 and bool(context.hostile_targets())
        start = time.monotonic()
        deadline = start + self._time_limit_sec
        # На отбор первого слоя уходит доля дедлайна, но не больше SCREEN_MAX_SEC:
        # RandomExplorer бесконечен, и оставь ему всё время, дереву не досталось бы ничего.
        screen = (min(self._time_limit_sec * SCREEN_SHARE, SCREEN_MAX_SEC) if deep
                  else self._time_limit_sec)
        until = start + screen
        best_actions: List[Action] = []
        best_score = 0.0
        considered = 0
        screen = FirstLayer(t.top_k) if deep else None
        for candidate in self._candidates(context):
            considered += 1
            if candidate.score > best_score:
                best_actions, best_score = candidate.actions, candidate.score
            if screen is not None:
                screen.add(candidate, context.src_cell)
            if time.monotonic() >= until:
                # Лимит исчерпан — фиксируем лучший из уже просмотренных (пункт 4).
                break
        value, depth, nodes, report = best_score, 1, 0, ""
        if screen is not None:
            found = Lookahead(context, scorer=self.scorer, deadline=deadline).search(screen.roots())
            if found is not None and found.depth >= 2:      # хуже greedy мы не делаем
                best_actions, best_score, value = found.actions, found.score, found.value
                depth, nodes, report = found.depth, found.nodes, found.report
        details = self.scorer.explain(context, best_actions) if best_actions else ""
        return PlanResult(actions=best_actions, score=best_score, value=value,
                          considered=considered, depth=depth, nodes=nodes, report=report,
                          details=" | ".join(filter(None, [details, report])))
