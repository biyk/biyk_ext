# tests/test_geometry.py — сеточная геометрия: смещения, расстояния, reach.
import pytest

from planner.geometry import (
    DIR_VECTORS, FEET_PER_CELL, REACH_GRID_TOLERANCE, apply_moves, cell_distance,
    within_reach,
)


def test_feet_per_cell_matches_grid():
    assert FEET_PER_CELL == 5


def test_apply_moves_composes_directions():
    assert apply_moves((0, 0), []) == (0, 0)
    assert apply_moves((0, 0), ["right", "right"]) == (0, 2)
    assert apply_moves((0, 0), ["down", "right", "downright"]) == (2, 2)
    assert apply_moves((3, 3), ["upleft"]) == (2, 2)


def test_apply_moves_rejects_unknown_direction():
    with pytest.raises(ValueError):
        apply_moves((0, 0), ["back"])


def test_dir_vectors_cover_eight_directions():
    assert set(DIR_VECTORS) == {
        "up", "down", "left", "right", "upleft", "upright", "downleft", "downright",
    }


def test_cell_distance_is_euclidean():
    assert cell_distance((0, 0), (0, 9)) == 9.0
    assert cell_distance((0, 0), (1, 1)) == pytest.approx(1.41421, abs=1e-4)


def test_within_reach_includes_diagonal_neighbours():
    # допуск аддитивный: полклетки (мерим от края токена, а не от центра)
    assert REACH_GRID_TOLERANCE == 0.5
    assert within_reach((0, 0), (0, 1), 1.0)      # ортогональный сосед
    assert within_reach((0, 0), (1, 1), 1.0)      # диагональный сосед (1.41)
    assert not within_reach((0, 0), (0, 2), 1.0)  # два клетки — мимо
    assert within_reach((0, 0), (0, 2), 2.0)      # reach 2 клетки достает (0,2)
    assert not within_reach((0, 0), (0, 3), 2.0)  # 15 футов вне 10-футовой досягаемости
    assert not within_reach((0, 0), (0, 4), 2.0)
