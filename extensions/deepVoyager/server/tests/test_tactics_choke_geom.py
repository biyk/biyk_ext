# tests/test_tactics_choke_geom.py — геометрия узостей (chokepoint) для hold_choke (Этап 4).
#
# chokepoint = артикуляционная точка графа проходимости (4-связность; рёбра режут move-стены,
# границы поля блокируют). Удаление узости разъединяет >=2 компоненты -> через неё проходят
# по одному. Открытое поле -> узостей нет; единственная дверь между половинами -> узость.
from conftest import make_npc, make_scene_payload, make_wall
from planner.context import BattleContext

from arent.tactics_geom import chokepoint_cells, is_choke


def _ctx(walls):
    npcs = [make_npc("A", 0, 0, disposition=-1, hp=30),
            make_npc("B", 450, 450, disposition=1, hp=30)]
    payload = make_scene_payload(walls=walls, npcs=npcs, token="B")
    payload.update({"src": "A"})
    return BattleContext.from_payload(payload)


def _vertical_door(gap_row, col=5, rows=10):
    """Сплошная вертикальная стена между col и col+1 (x=(col+1)*50) с одним проёмом на gap_row."""
    out = []
    for r in range(rows):
        if r == gap_row:
            continue
        out.append(make_wall(f"w{r}", (col + 1) * 50, r * 50, (col + 1) * 50, (r + 1) * 50,
                             move=1, sight=1))
    return out


def test_open_field_has_no_chokepoints():
    cells = chokepoint_cells(_ctx([]))
    assert cells == frozenset()


def test_single_doorway_is_chokepoint():
    ctx = _ctx(_vertical_door(gap_row=5))
    ck = chokepoint_cells(ctx)
    # стена x=300 делит col5|col6; единственный переход на row5 -> клетки (5,5)-(5,6) узости
    assert (5, 5) in ck and (5, 6) in ck
    # клетка в глубине половины НЕ узость (удаление сохраняет связность региона)
    assert (0, 0) not in ck and (9, 9) not in ck
    assert is_choke(ctx, (5, 5)) is True
    assert is_choke(ctx, (0, 0)) is False


def _wall_row(r, col):
    return make_wall(f"w{r}", (col + 1) * 50, r * 50, (col + 1) * 50, (r + 1) * 50,
                     move=1, sight=1)


def test_wide_gap_has_no_single_chokepoint():
    # проём в 3 ряда: удаление любой одной клетки оставляет обе половины связными
    walls = [_wall_row(r, 5) for r in range(10) if r not in (4, 5, 6)]
    ck = chokepoint_cells(_ctx(walls))
    assert (4, 5) not in ck and (5, 5) not in ck and (6, 5) not in ck
