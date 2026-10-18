# tests/test_context.py — разбор и валидация payload в доменную модель.
import pytest

from conftest import make_npc, make_scene_payload, make_wall
from planner.context import BattleContext


def test_parses_full_payload(scene_payload):
    ctx = BattleContext.from_payload(scene_payload)
    assert ctx.scene.grid_size == 50
    assert (ctx.scene.rows, ctx.scene.cols) == (10, 10)
    assert ctx.src_id == "A" and ctx.target_id == "B"
    assert len(ctx.tokens) == 2 and ctx.walls == ()

    a = ctx.token("A")
    assert (a.center_x, a.center_y) == (25.0, 25.0)
    assert a.is_alive and a.disposition == 0
    assert ctx.src.id == "A"


def test_cell_of_maps_pixels_to_row_col(scene_payload):
    ctx = BattleContext.from_payload(scene_payload)
    assert ctx.scene.cell_of(25, 25) == (0, 0)
    assert ctx.scene.cell_of(475, 25) == (0, 9)
    assert ctx.scene.cell_of(475, 475) == (9, 9)


def test_dead_token_not_alive():
    payload = make_scene_payload(npcs=[make_npc("A", 0, 0, hp=0), make_npc("B", 450, 0)])
    ctx = BattleContext.from_payload(payload)
    assert not ctx.token("A").is_alive


def test_wall_move_flags():
    payload = make_scene_payload(walls=[
        make_wall("w1", 0, 0, 50, 0, move=1),
        make_wall("w2", 0, 50, 50, 50, move=0),
        make_wall("w3", 0, 100, 50, 100, move=None),  # None из Foundry-данных
    ])
    ctx = BattleContext.from_payload(payload)
    assert ctx.walls[0].blocks_movement
    assert not ctx.walls[1].blocks_movement
    assert not ctx.walls[2].blocks_movement


@pytest.mark.parametrize("payload", [None, {}, {"src": "A"}, {"src": "A", "data": {}}])
def test_invalid_payload_raises_value_error(payload):
    with pytest.raises(ValueError):
        BattleContext.from_payload(payload)


def test_empty_npcs_rejected():
    with pytest.raises(ValueError):
        BattleContext.from_payload(make_scene_payload(npcs=[]))


def test_wall_without_points_rejected():
    bad_wall = {"id": "w1", "points": {"A": {"x": 0, "y": 0}}, "move": 1}
    with pytest.raises(ValueError):
        BattleContext.from_payload(make_scene_payload(walls=[bad_wall]))


def test_src_property_raises_when_missing(scene_payload):
    scene_payload["src"] = "ghost"
    ctx = BattleContext.from_payload(scene_payload)
    with pytest.raises(ValueError):
        _ = ctx.src
