# tests/test_tactics_ctx_choke.py — build_step_ctx наполняет at_choke_*, hold_choke срабатывает.
#
# Детекторы _hold_choke/_leave_choke читают StepCtx.at_choke_before/at_choke_after. Этап 4
# обязал build_step_ctx вычислять их из геометрии карты (tactics_geom.is_choke), иначе тактика
# не наполняется и гейт cover_shoot/hold_choke meaningless. Проверяем на вертикальной стене с
# единственной дверью: клетка проёма (5,5) — узость.
from conftest import make_npc, make_scene_payload, make_wall, make_weapon
from planner.context import BattleContext
from planner.sim import Simulation

from arent.tactics import Tag
from arent.tactics_ctx import build_step_ctx
from arent.tactics_detect import detect


def _door_ctx():
    """Стена x=300 (col5|col6) с единственным проёмом на row5 -> узости (5,5)/(5,6)."""
    walls = [make_wall(f"w{r}", 300, r * 50, 300, (r + 1) * 50, move=1, sight=1)
             for r in range(10) if r != 5]
    npcs = [make_npc("A", 250, 250, disposition=-1, hp=20, speed=30, damage="1d8"),
            make_npc("B", 0, 0, disposition=1, hp=20, speed=0, damage="1d8")]
    payload = make_scene_payload(walls=walls, npcs=npcs,
                                 weapons=[make_weapon("sword", damage="1d6+2")], token="B")
    return Simulation.of(BattleContext.from_payload(payload))


def test_build_step_ctx_marks_actor_in_choke_cell():
    sim = _door_ctx()
    units = sim.units
    hp_max = {uid: u.hp for uid, u in units.items()}
    choke_cell = units[sim.hero_id].cell
    assert choke_cell == (5, 5)
    ctx = build_step_ctx(sim, units, units, sim.hero_id, choke_cell, target_id="B",
                         attacked=True, round_index=0, hp_max=hp_max)
    assert ctx.at_choke_before is True and ctx.at_choke_after is True


def test_hold_choke_fires_when_staying_and_attacking_in_choke():
    sim = _door_ctx()
    units = sim.units
    hp_max = {uid: u.hp for uid, u in units.items()}
    choke_cell = units[sim.hero_id].cell
    ctx = build_step_ctx(sim, units, units, sim.hero_id, choke_cell, target_id="B",
                         attacked=True, round_index=0, hp_max=hp_max)
    det = detect(ctx)
    assert Tag.hold_choke.value in det.applicable
    assert Tag.hold_choke.value in det.fired


def test_leave_choke_violated_when_stepping_out_of_choke():
    sim = _door_ctx()
    units = sim.units
    hp_max = {uid: u.hp for uid, u in units.items()}
    out_cell = (5, 4)                                   # шаг с узости вглубь половины (не узость)
    ctx = build_step_ctx(sim, units, units, sim.hero_id, out_cell, target_id="B",
                         attacked=False, round_index=0, hp_max=hp_max)
    det = detect(ctx)
    assert ctx.at_choke_before is True and ctx.at_choke_after is False
    assert Tag.hold_choke.value in det.applicable and Tag.hold_choke.value not in det.fired
    assert "leave_choke" in det.violated


def test_no_choke_when_open_field():
    """Без стен (открытое поле) at_choke_* ложны и hold_choke неприменим."""
    npcs = [make_npc("A", 250, 250, disposition=-1, hp=20, speed=30, damage="1d8"),
            make_npc("B", 0, 0, disposition=1, hp=20, speed=0, damage="1d8")]
    payload = make_scene_payload(walls=[], npcs=npcs,
                                 weapons=[make_weapon("sword", damage="1d6+2")], token="B")
    sim = Simulation.of(BattleContext.from_payload(payload))
    units = sim.units
    hp_max = {uid: u.hp for uid, u in units.items()}
    cell = units[sim.hero_id].cell
    ctx = build_step_ctx(sim, units, units, sim.hero_id, cell, target_id="B",
                         attacked=True, round_index=0, hp_max=hp_max)
    det = detect(ctx)
    assert ctx.at_choke_before is False
    assert Tag.hold_choke.value not in det.applicable
