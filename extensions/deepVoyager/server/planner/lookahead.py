# planner/lookahead.py — многошаговый выбор линии хода (пункт 5 todo.md).
#
# Итеративное углубление: слой 1 считается как раньше (жадный перебор в service.py),
# затем наращиваем глубину 2, 3, … пока укладываемся в limits.planTimeLimitSec.
# Не успели — остаётся результат предыдущей глубины, поэтому план никогда не хуже
# сегодняшнего greedy. Ветки первого слоя — топ-K кандидатов перебора (цель + финальная
# клетка разные), в глубине — компактный набор hero_options(): иначе дерево O(K^R)
# не считается вообще. Значение линии = сумма по раундам: очки Scorer + штрафы симуляции.
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from planner.action import ACTION_MOVE, Action
from planner.context import BattleContext
from planner.geometry import DIR_VECTORS, Cell, apply_moves
from planner.points import tuning
from planner.scoring import Scorer
from planner.sim import Simulation
from planner.strategy import Candidate

#: долю дедлайна, которую можно потратить на отбор кандидатов первого слоя
SCREEN_SHARE = 0.6
#: и в секундах: случайные прогулки приносят всё новые, но не более удачные планы,
#: поэтому остаток бюджета отдаём дереву
SCREEN_MAX_SEC = 1.5


class _Timeout(Exception):
    """Дедлайн наступил в ходе глубины: частично раскрытый слой отбрасываем целиком."""


@dataclass(frozen=True)
class SearchResult:
    """Лучшая линия: действия первого раунда, её значение и диагностика для лога."""
    actions: List[Action] = field(default_factory=list)
    score: float = 0.0          # очки первого раунда (то, что видит Scorer)
    value: float = 0.0          # значение линии целиком
    depth: int = 1
    nodes: int = 0
    report: str = ""


class FirstLayer:
    """Топ-K кандидатов перебора с разнообразием: не восемь путей в одну клетку."""

    def __init__(self, top_k: int):
        self._top_k = max(1, int(top_k))
        self._best: Dict[Tuple[str, Cell], Candidate] = {}

    def add(self, candidate: Candidate, start: Cell) -> None:
        key = (candidate.target_id, self.end_cell(candidate.actions, start))
        prev = self._best.get(key)
        if prev is None or candidate.score > prev.score:
            self._best[key] = candidate
        if len(self._best) > 4 * self._top_k:
            self._prune()

    def _prune(self) -> None:
        keep = sorted(self._best.items(), key=lambda kv: -kv[1].score)[:2 * self._top_k]
        self._best = dict(keep)

    def roots(self) -> List[Candidate]:
        return sorted(self._best.values(), key=lambda c: -c.score)[: self._top_k]

    @staticmethod
    def end_cell(actions: Sequence[Action], start: Cell) -> Cell:
        dirs = [a.conf.get("direction") for a in actions if a.action == ACTION_MOVE]
        return apply_moves(start, [d for d in dirs if d in DIR_VECTORS])


class Lookahead:
    """Перебор глубины: коридор первого слоя задает service, развилки — симуляция."""

    def __init__(self, context: BattleContext, scorer: Optional[Scorer] = None,
                 deadline: Optional[float] = None):
        self._ctx = context
        self._scorer = scorer or Scorer()
        self._deadline = (time.monotonic() + tuning().plan_time_limit_sec
                          if deadline is None else deadline)
        self._nodes = 0

    def search(self, first_layer: Sequence[Candidate]) -> Optional[SearchResult]:
        """Лучшая линия глубин 2..max_rounds; None, если на глубину нет времени вовсе."""
        roots = list(first_layer)
        if not roots:
            return None
        state = Simulation.of(self._ctx)
        best: Optional[Tuple[float, list, int]] = None
        nodes = 0
        for depth in range(2, tuning().max_rounds + 1):
            self._nodes = 0
            try:
                value, line = self._best_root(state, roots, depth)
            except _Timeout:
                break                      # частично раскрытая глубина не годится вовсе
            nodes += self._nodes
            best = (value, line, depth)
            if time.monotonic() >= self._deadline:
                break
        if best is None:
            return None
        value, line, depth = best
        return SearchResult(actions=list(line[0][0]), score=line[0][1], value=value,
                            depth=depth, nodes=nodes, report=self._format(line, value))

    def _best_root(self, state: Simulation, roots: Sequence[Candidate],
                   depth: int) -> Tuple[float, list]:
        """Среди кандидатов первого слоя — линия с максимумом значения на глубине depth."""
        best: Optional[Tuple[float, list]] = None
        for root in roots:
            total, line = self._walk(state, root.actions, depth)
            if best is None or total > best[0]:
                best = (total, line)
        if best is None:
            raise _Timeout()
        return best

    def _walk(self, state: Simulation, actions: List[Action],
              remaining: int) -> Tuple[float, list]:
        """Один узел: играем раунд, затем лучший из компактных ходов героя вглубь."""
        if time.monotonic() >= self._deadline:
            raise _Timeout()
        score = self._scorer.score(state.context_for(state.hero_id), actions)
        state, value = state.advance(actions)
        self._nodes += 1
        here = [(actions, score, value - score)]
        if remaining <= 1 or state.hero_dead:
            return value, here
        best: Optional[Tuple[float, list]] = None
        for tail_actions in state.hero_options():
            total, tail = self._walk(state, tail_actions, remaining - 1)
            if best is None or value + total > best[0]:
                best = (value + total, here + tail)
        return best if best else (value, here)

    @staticmethod
    def _format(line: list, value: float) -> str:
        """«R1 +31/-0 → R2 +1/-0 = 32» — очки и штраф каждого раунда и итог линии."""
        parts = [f"R{i} {score:+g}/{penalty:+g}"
                 for i, (_a, score, penalty) in enumerate(line, 1)]
        return " → ".join(parts) + f" = {value:g}"
