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

# Допуск в полклетки: дистанцию меряем между центрами клеток, а в D&D 5e
# считают от края токена — плюс диагональный сосед (1.41) должен попадать
# в reach 1 клетка (как и в utils/combat.js для melee-атак).
REACH_GRID_TOLERANCE = 0.5


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
    """Достанет ли атака из клетки a в клетку b при дальности reach_cells."""
    return cell_distance(a, b) <= reach_cells + REACH_GRID_TOLERANCE
