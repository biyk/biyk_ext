# planner/geometry.py — сеточная геометрия: направления, смещения, расстояние по прямой.
import math
from typing import Dict, Iterable, Tuple

Cell = Tuple[int, int]  # (row, col)

FEET_PER_CELL = 5  # одна клетка сетки = 5 футов

# Векторы 8 направлений в (row, col): up = меньше y = меньше row
DIR_VECTORS: Dict[str, Cell] = {
    "up": (-1, 0),
    "down": (1, 0),
    "left": (0, -1),
    "right": (0, 1),
    "upleft": (-1, -1),
    "upright": (-1, 1),
    "downleft": (1, -1),
    "downright": (1, 1),
}

# Диагональ соседней клетки = 1.41 клетки; допуск 1.5 — чтобы melee-атака
# считалась возможной против соседей по диагонали (как в D&D 5e).
DIAGONAL_REACH_TOLERANCE = 1.5


def apply_moves(start: Cell, directions: Iterable[str]) -> Cell:
    """Клетка после применения последовательности направлений."""
    row, col = start
    for d in directions:
        vec = DIR_VECTORS.get(d)
        if vec is None:
            raise ValueError(f"Недопустимое направление: {d!r}")
        row += vec[0]
        col += vec[1]
    return row, col


def cell_distance(a: Cell, b: Cell) -> float:
    """Расстояние по прямой между центрами клеток, в клетках сетки."""
    return math.dist(a, b)


def within_reach(a: Cell, b: Cell, reach_cells: float) -> bool:
    """Достанет ли атака из клетки a до клетки b при дальности reach_cells."""
    return cell_distance(a, b) <= reach_cells * DIAGONAL_REACH_TOLERANCE
