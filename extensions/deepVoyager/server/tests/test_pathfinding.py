# tests/test_pathfinding.py — адаптер PathfindingService над libs/quin.py.
from conftest import make_npc, make_scene_payload, make_wall
from planner.context import BattleContext
from planner.geometry import apply_moves
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
    # стена x=200 от y=0 до y=250: снизу зазор — прямой путь [right]*9 закрыт;
    # маршрут обязан обойти стену и дойти до клетки цели (0,9)
    payload = make_scene_payload(walls=[make_wall("w", 200, 0, 200, 250)])
    path = service_for(payload).path_to_target()
    assert path and path != [RIGHT] * 9
    assert apply_moves((0, 0), path) == (0, 9)


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
    # путь A→B: клетка (0,1) занята C → напрямую нельзя, обход (теперь и диагоналями)
    path = service_for(payload).path_to_target()
    assert path and path != [RIGHT, RIGHT]
    assert set(path) <= {RIGHT, "left", "down", "up", "upleft", "upright",
                         "downleft", "downright"}


def test_diagonal_is_shortest_and_preferred():
    # цель по диагонали (клетка (2,2)): 2 шага downright вместо 4 ортогональных
    payload = make_scene_payload(npcs=[make_npc("A", 0, 0), make_npc("B", 100, 100)])
    assert service_for(payload).path_to_target() == ["downright", "downright"]


def test_diagonal_cannot_cut_between_wall_corners():
    # стены пересекают границы клеток (0,1) и (1,0) — те недоступны; диагональ
    # (0,0)->(1,1) проходила бы ровно между их углами — правило D&D 5e её
    # запрещает, иных путей из угла нет -> пустой маршрут
    walls = [make_wall("wv", 75, -40, 75, 40), make_wall("wh", -40, 75, 40, 75)]
    payload = make_scene_payload(walls=walls,
                                 npcs=[make_npc("A", 0, 0), make_npc("B", 50, 50)])
    assert service_for(payload).path_to_target() == []
