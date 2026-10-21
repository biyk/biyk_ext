# planner/los.py — единый механизм линии видимости (F-C).
#
# Раньше LOS считала только arent/observe (наблюдение), а исполнение урона (planner/sim) и
# маски (slots/slots_v3) смотрели лишь на дистанцию: модель могла «видеть» стену в наблюдении,
# но удар сквозь неё проходил, а маска разрешала выстрел, который симуляция затем обнуляла.
# Здесь ОДНО правило на всех: прямая между центрами клеток не пересекает ни одной стены с
# флагом sight. Наблюдение, маски и исполнение вызывают has_los/los_clear из этого модуля,
# поэтому «что видно» и «что реально заденет» больше не расходятся.
#
# Зависимости только вниз по слоям (libs/quin + planner.*): planner не тянет arent, цикл
# импортов невозможен. arent/observe импортирует отсюда и реэкспортирует старые имена.
from typing import List, Optional, Tuple

from libs.quin import SimplePathfinder
from planner.context import BattleContext
from planner.geometry import Cell, within_reach

Point = Tuple[float, float]
Segment = Tuple[Point, Point]


def sight_segments(ctx: BattleContext) -> List[Segment]:
    """Стены, мешающие обзору: тот же геометрический тест, что у quin, но по флагу sight."""
    return [((w.ax, w.ay), (w.bx, w.by)) for w in ctx.walls if w.sight > 0]


def _center(ctx: BattleContext, cell: Cell) -> Point:
    gs = ctx.scene.grid_size
    return (cell[1] + 0.5) * gs, (cell[0] + 0.5) * gs


def has_los(ctx: BattleContext, a: Cell, b: Cell, segments: List[Segment]) -> bool:
    """Видно ли центр клетки b из центра клетки a: прямая не пересекает ни одной стены."""
    p1, p2 = _center(ctx, a), _center(ctx, b)
    return not any(SimplePathfinder._segment_intersect(p1, p2, s[0], s[1]) for s in segments)


def los_clear(ctx: BattleContext, a: Cell, b: Cell,
              segments: Optional[List[Segment]] = None) -> bool:
    """has_los с отложенным сбором стен: когда список сегментов не передан, считаем его сами."""
    return has_los(ctx, a, b, sight_segments(ctx) if segments is None else segments)


def striking_distance(ctx: BattleContext, from_cell: Cell, to_cell: Cell, reach_cells: float,
                      segments: Optional[List[Segment]] = None) -> bool:
    """Единое правило удара (F-C): цель ДОСТУПНА, если дотягиваем по дистанции И есть линия
    видимости из позиции удара. Один вызов и для масок, и для исполнения урона."""
    return (within_reach(from_cell, to_cell, reach_cells)
            and los_clear(ctx, from_cell, to_cell, segments))
