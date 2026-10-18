# tests/test_context.py — разбор и валидация payload в доменную модель.
import pytest

from conftest import make_npc, make_scene_payload, make_wall, make_weapon
from planner.context import BattleContext


def test_parses_full_payload(scene_payload):
    ctx = BattleContext.from_payload(scene_payload)
    assert ctx.scene.grid_size == 50
    assert (ctx.scene.rows, ctx.scene.cols) == (10, 10)
    assert ctx.src_id == "A" and ctx.target_id == "B"
    assert len(ctx.tokens) == 2 and ctx.walls == ()

    a = ctx.token("A")
    assert (a.center_x, a.center_y) == (25.0, 25.0)
    assert a.is_alive and a.disposition == -1
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


def test_defaults_and_optional_step4_fields():
    ctx = BattleContext.from_payload(make_scene_payload())
    assert ctx.speed_steps == 6      # 30 футов / 5
    assert ctx.weapons == ()         # без оружия атака невозможна

    ctx = BattleContext.from_payload(
        {**make_scene_payload(weapons=[make_weapon("shortbow", sure_ft=30, doubt_ft=120)]),
         "speed": 50})
    assert ctx.speed_steps == 10
    assert [w.id for w in ctx.weapons] == ["shortbow"]
    assert (ctx.weapons[0].sure_ft, ctx.weapons[0].doubt_ft) == (30.0, 120.0)
    assert ctx.weapons[0].attack_bonus == 2 and ctx.weapons[0].damage == "1d6+2"
    assert ctx.weapon("shortbow") is ctx.weapons[0]
    assert ctx.weapon("ghost") is None


def test_weapon_without_id_skipped():
    ctx = BattleContext.from_payload(
        make_scene_payload(weapons=[{"name": "мусор"}, make_weapon("bite")]))
    assert [w.id for w in ctx.weapons] == ["bite"]


def test_melee_defaults_sure_equals_doubt():
    # у ближнего боя сомнительная == уверенная (5 футов = 1 клетка)
    ctx = BattleContext.from_payload(make_scene_payload(weapons=[make_weapon("club")]))
    assert (ctx.weapons[0].sure_ft, ctx.weapons[0].doubt_ft) == (5.0, 5.0)


def test_hostile_rules():
    # босс (-2) воюет с 1; друзья (-1), нейтральные (0) и мёртвые — не цели
    npcs = [
        make_npc("A", 0, 0, disposition=-2),
        make_npc("P", 100, 0, disposition=1),
        make_npc("M", 150, 0, disposition=-1),
        make_npc("N", 200, 0, disposition=0),
        make_npc("D", 250, 0, disposition=1, hp=0),
    ]
    ctx = BattleContext.from_payload(make_scene_payload(npcs=npcs))
    assert [t.id for t in ctx.hostile_targets()] == ["P"]


def test_explicit_target_added_to_hostiles():
    # target_id из запроса становится кандидатом, даже если формально нейтрален
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("N", 200, 0, disposition=0)]
    payload = {**make_scene_payload(npcs=npcs), "token": "N"}
    ctx = BattleContext.from_payload(payload)
    assert [t.id for t in ctx.hostile_targets()] == ["N"]


def test_token_keeps_name():
    # Имя токена нужно для логов: «праща → Стражник (1)» вместо непонятного id.
    npcs = [make_npc("A", 0, 0, disposition=-1, name="Кобольд"),
            make_npc("B", 450, 0, disposition=1, name="Стражник (1)")]
    ctx = BattleContext.from_payload(make_scene_payload(npcs=npcs))
    assert ctx.token("B").name == "Стражник (1)"
    assert ctx.src.name == "Кобольд"

    # Старый клиент без поля name: имя остаётся пустым, а не падает
    legacy = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 450, 0, disposition=1)]
    for entry in legacy:
        entry.pop("name")
    ctx = BattleContext.from_payload(make_scene_payload(npcs=legacy))
    assert ctx.token("B").name == ""
