# tests/test_pathfinding.py — адаптер PathfindingService над libs/quin.py.
from conftest import make_npc, make_scene_payload, make_wall
from planner.context import BattleContext
from planner.pathfinding import PathfindingService

RIGHT = "right"


def service_for(payload):
    return PathfindingService(BattleContext.from_payload(payload))


def test_free_path_is_straight_line(scene_payload):
    assert service_for(scene_payload).path_to_target() == [RIGHT] * 9


def test_solid_wall_blocks_path():
    payload = make_scene_payload(walls=[make_wall("w", 200, 0, 200, 500)])
    assert service_for(payload).path_to_target() == []


def test_detour_around_wall_with_gap():
    payload = make_scene_payload(walls=[make_wall("w", 200, 0, 200, 250)])
    path = service_for(payload).path_to_target()
    assert len(path) > 9 and "down" in path and RIGHT in path


def test_unknown_ids_return_empty_not_raise():
    assert service_for(make_scene_payload()).find_path("nope", "B") == []


def test_path_to_target_without_target_id():
    payload = make_scene_payload()
    payload["token"] = None
    assert service_for(payload).path_to_target() == []


def test_occupied_cell_forces_detour():
    # B зажат стеной сверху и снизу — проход только через пустую row 1 нет:
    # стена y=0..50 у клетки A слева сверху не мешает, проверяем занятость клетки C
    payload = make_scene_payload(npcs=[
        make_npc("A", 0, 0), make_npc("B", 100, 0), make_npc("C", 50, 0),
    ])
    # путь A→B: клетка (0,1) занята C → напрямую нельзя, обход вниз/вправо/вверх
    path = service_for(payload).path_to_target()
    assert path and path != [RIGHT, RIGHT]
    assert set(path) <= {RIGHT, "left", "down", "up"}
