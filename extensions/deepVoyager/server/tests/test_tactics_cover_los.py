# tests/test_tactics_cover_los.py — LOS-укрытие для cover_shoot (Этап 4).
#
# enemy_cover(ctx, cell, foes) == True, когда НИ ОДИН враг не имеет линии видимости до cell
# (стена с флагом sight ломает прямую). Это ровно семантика детектора cover_shoot (cover_after),
# но как чистая геометрия: и наблюдение (encode_v3), и tactics_ctx считают укрытие отсюда.
from conftest import make_npc, make_scene_payload, make_wall
from planner.context import BattleContext

from arent.tactics_geom import enemy_cover


def _ctx(walls):
    npcs = [make_npc("A", 0, 0, disposition=-1, hp=30),
            make_npc("B", 150, 0, disposition=1, hp=30)]      # клетка (0,3)
    payload = make_scene_payload(walls=walls, npcs=npcs, token="B")
    payload.update({"src": "A"})
    return BattleContext.from_payload(payload)


def _sight_wall():
    return make_wall("w", 50, 0, 50, 50, move=0, sight=1)      # x=50 ломает LOS, не ходьбу


def test_cover_behind_wall_true():
    ctx = _ctx([_sight_wall()])
    # из (0,0) в (0,3) прямой нет (стена x=50) -> (0,0) под укрытием от B
    assert enemy_cover(ctx, (0, 0), [(0, 3)]) is True


def test_cover_when_visible_false():
    ctx = _ctx([_sight_wall()])
    # выглянул на (0,1) [центр 75] -> до (0,3) прямая есть -> укрытия нет
    assert enemy_cover(ctx, (0, 1), [(0, 3)]) is False


def test_cover_no_enemies_false():
    ctx = _ctx([_sight_wall()])
    assert enemy_cover(ctx, (0, 0), []) is False


def test_cover_open_field_false():
    ctx = _ctx([])
    assert enemy_cover(ctx, (0, 0), [(0, 3)]) is False
