# planner/explore.py — пошаговый перебор хода вместо обрезанного quin-маршрута.
#
# Источники кандидатов (порядок = приоритет при равных очках, замена strict >):
#  • BruteForceExplorer — BFS по всем клеткам, достижимым за скорость хода;
#    путь к выбранной клетке кратчайший, поэтому движение не «прыгает»;
#  • RandomExplorer — случайные легальные прогулки до дедлайна сервиса.
# Валидация клеток переиспользуется из libs/quin.py (стены, занятость, углы).
# Действия пока move/use/target — _candidate расширяем под новые типы действий.
import random
from typing import Dict, List, Optional, Tuple

from planner.action import Action, move_action, target_action, use_action
from planner.context import BattleContext
from planner.geometry import cell_distance, within_reach
from planner.pathfinding import PathfindingService
from planner.scoring import Scorer
from planner.strategy import Candidate

Cell = Tuple[int, int]


def legal_steps(pf, cr: int, cc: int, src_id: str, src_cell: Cell,
                occupied=frozenset()) -> List[Tuple[str, Cell]]:
    """Легальные одношаговые ходы (направление, клетка) из (cr, cc).

    Правила те же, что в SimplePathfinder.find_path: границы, стены, занятые
    клетки, правило углов D&D 5e; ребро из стартовой клетки игнорирует
    прямоугольник самого токена (иначе он блокировал бы первый шаг).
    """
    out = []
    for dr, dc in pf.dirs:
        nr, nc = cr + dr, cc + dc
        if not (0 <= nr < pf.rows and 0 <= nc < pf.cols) or (nr, nc) in occupied:
            continue
        if dr and dc and not (pf._cell_valid(cr, nc, skip_npcs=True)
                              and pf._cell_valid(nr, cc, skip_npcs=True)):
            continue
        if not pf._cell_valid(nr, nc):
            continue
        ignores = (src_id,) if (cr, cc) == src_cell else ()
        if not pf._edge_valid(cr, cc, nr, nc, ignores):
            continue
        out.append((pf.dir_names[(dr, dc)], (nr, nc)))
    return out


def reachable_paths(pf, start: Cell, src_id: str, max_steps: int) -> Dict[Cell, List[str]]:
    """BFS: клетка -> кратчайшая последовательность направлений (≤ max_steps клеток).

    Включает саму стартовую клетку (пустой путь). Клетки существ исключены:
    _cell_valid не пускает в прямоугольник NPC — вставать на существо нельзя.
    """
    paths: Dict[Cell, List[str]] = {start: []}
    frontier = [start]
    for _ in range(max_steps):
        nxt: List[Cell] = []
        for cr, cc in frontier:
            for d, cell in legal_steps(pf, cr, cc, src_id, start, occupied=paths.keys()):
                if cell in paths:
                    continue
                paths[cell] = paths[(cr, cc)] + [d]
                nxt.append(cell)
        frontier = nxt
    return paths


def _candidate(ctx: BattleContext, scorer: Scorer, kind: str,
               cell: Cell, dirs: List[str], enemies) -> Candidate:
    """Действия target -> move... -> атака (если цель в досягаемости) и их оценка."""
    nearest = min(enemies, key=lambda e: cell_distance(cell, ctx.cell_of(e)))
    actions: List[Action] = [target_action(nearest.id)]
    actions += [move_action(d) for d in dirs]
    if ctx.weapon_id and within_reach(cell, ctx.cell_of(nearest), ctx.reach_cells):
        actions.append(use_action(ctx.weapon_id))
    return Candidate(kind=kind, target_id=nearest.id, actions=actions,
                     score=scorer.score(ctx, actions))


class BruteForceExplorer:
    """«Тупой перебор»: кандидат на каждую достижимую за ход клетку."""

    def __init__(self, context: BattleContext, pathfinder: Optional[PathfindingService] = None,
                 scorer: Optional[Scorer] = None):
        self._ctx = context
        self._pf = (pathfinder or PathfindingService(context))._finder
        self._scorer = scorer or Scorer()

    def enumerate(self):
        enemies = self._ctx.hostile_targets()
        if not enemies:
            return
        cells = reachable_paths(self._pf, self._ctx.src_cell,
                                self._ctx.src_id, self._ctx.speed_steps)
        # детерминированный порядок: сначала кратчайшие пути, затем координаты
        for cell, dirs in sorted(cells.items(), key=lambda kv: (len(kv[1]), kv[0])):
            yield _candidate(self._ctx, self._scorer, "brute", cell, dirs, enemies)


class RandomExplorer:
    """Случайные легальные прогулки; бесконечный источник (остановит дедлайн)."""

    def __init__(self, context: BattleContext, pathfinder: Optional[PathfindingService] = None,
                 scorer: Optional[Scorer] = None, rng: Optional[random.Random] = None):
        self._ctx = context
        self._pf = (pathfinder or PathfindingService(context))._finder
        self._scorer = scorer or Scorer()
        self._rng = rng or random.Random()

    def enumerate(self):
        enemies = self._ctx.hostile_targets()
        if not enemies:
            return
        while True:
            cell, dirs = self._ctx.src_cell, []
            for _ in range(self._ctx.speed_steps):
                if dirs and self._rng.random() < 0.25:
                    break  # иногда останавливаемся раньше — атака с текущей клетки
                options = self._steps_from(cell)
                if not options:
                    break
                d, cell = self._rng.choice(options)
                dirs.append(d)
            yield _candidate(self._ctx, self._scorer, "random", cell, dirs, enemies)

    def _steps_from(self, cell: Cell):
        return legal_steps(self._pf, cell[0], cell[1],
                           self._ctx.src_id, self._ctx.src_cell)
