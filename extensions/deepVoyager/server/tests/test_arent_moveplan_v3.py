# tests/test_arent_moveplan_v3.py — F-B: SCHEMA=3 выражает «выстрелил — спрятался».
#
# v2 сворачивает все MOVE в конечную клетку и бьёт из неё (sim.apply_actor), поэтому удар с
# исходной позиции с последующим отступлением невыразим. Здесь:
#   1) apply_actor_seq исполняет действия по порядку: USE резолвится из клетки В МОМЕНТ удара;
#   2) слоты v3 перечисляют пары (attack_cell, end_cell) в пределах бюджета движения;
#   3) decode -> target, move(до атаки), use, move(уход); label_of восстанавливает пару;
#   4) attackable_v3 меряет дальность от attack_cell, а не от end_cell;
#   5) все 5 тактических последовательностей представимы и исполнимы;
#   6) v2-совместимость: без отступления (end==attack) seq совпадает с apply_actor;
#   7) dims3() отличается от v2 -> старые веса не загрузятся (схема bump).
import pytest

from conftest import make_npc, make_scene_payload, make_weapon
from planner.action import move_action, target_action, use_action
from planner.context import BattleContext
from planner.geometry import apply_moves, cell_distance, within_reach
from planner.points import tuning
from planner.sim import Simulation
from arent import spec, spec3
from arent import slots_v3
from arent.observe import observe

DAMAGE_SWORD = "1d6+2"          # ожидание 5.5, * hit_chance 0.65 = 3.575


def _ctx(npcs, weapons, speed=30, token="A"):
    payload = {**make_scene_payload(npcs=npcs, weapons=weapons or []), "speed": speed,
               "src": token, "token": token}
    return BattleContext.from_payload(payload)


def _adjacent():
    """Герой A в (0,5), враг B вплотную в (0,6); меч reach 1 клетка."""
    npcs = [make_npc("A", 250, 0, disposition=-1, hp=20),
            make_npc("B", 300, 0, disposition=1, hp=20, damage="1d8")]
    return _ctx(npcs, [make_weapon("sword", sure_ft=5, damage=DAMAGE_SWORD)])


#--- 1/6. последовательное исполнение vs свёрнутое (P0-2) --------------------
def test_attack_from_origin_then_retreat_damages_under_seq_only():
    ctx = _adjacent()
    sim = Simulation.of(ctx)
    hurt = [target_action("B"), use_action("sword"), move_action("left"), move_action("left")]
    seq = sim.apply_actor_seq("A", hurt)          # удар с (0,5) по соседу -> попадание, затем уход
    collapsed = sim.apply_actor("A", hurt)        # v2: сначала отход на (0,3), бьёт оттуда -> мимо
    dmg = 5.5 * tuning().hit_chance
    assert seq.hp["B"] == pytest.approx(20 - dmg)
    assert collapsed.hp["B"] == pytest.approx(20)          # в2 не умеет такую тактику
    assert seq.cells["A"] == (0, 3)                        # финальная позиция — после отступления


def test_seq_equals_apply_actor_when_no_retreat():
    ctx = _adjacent()
    sim = Simulation.of(ctx)
    strike = [target_action("B"), move_action("left"), use_action("sword")]
    # end==attack (отступления нет): порядок move->use совпадает со свёрнутым
    assert sim.apply_actor_seq("A", strike).hp["B"] == pytest.approx(
        sim.apply_actor("A", strike).hp["B"])


#--- 2/4. слоты v3: бюджет и дальность от attack_cell ------------------------
def _slots(ctx):
    order = Simulation.of(ctx).initiative_order
    obs = observe(ctx, order, ctx.src_id)
    return slots_v3.build(ctx, obs), ctx, obs


def test_moveplans_respect_move_budget():
    ctx = _ctx([make_npc("A", 250, 250, disposition=-1, hp=20),
                make_npc("B", 500, 250, disposition=1, hp=20)], [make_weapon("bow", ranged=300,
                       sure_ft=10, doubt_ft=30, damage="1d8+2")], speed=30)
    slots, _c, _o = _slots(ctx)
    assert slots.plans, "нет ни одного move-plan'а"
    speed_steps = ctx.speed_steps
    for p in slots.plans:
        assert p["costTotal"] <= speed_steps
        assert p["costIn"] == len(p["dirs_in"]) and p["costOut"] == len(p["dirs_out"])
    hit_and_run = [p for p in slots.plans
                   if p["attack_cell"] != (ctx.src_cell) and p["end_cell"] != p["attack_cell"]]
    assert hit_and_run, "нет ни одного «подойти — ударить — отступить» плана"


def test_attackable_v3_uses_attack_cell_not_end_cell():
    ctx = _adjacent()
    slots, c, _o = _slots(ctx)
    foe_cell = c.cell_of(c.token("B"))
    b_idx = next(i for i, t in enumerate(slots.targets) if t["id"] == "B")
    near = next(p for p in slots.plans if cell_distance(p["attack_cell"], foe_cell) <= 1.0)
    plan_i = slots.plans.index(near)
    assert slots_v3.attackable_v3(slots, c, plan_i, b_idx, 0) is True
    # план, где позиция АТАКИ далеко от врага, нелегален даже если end рядом
    far = next((p for p in slots.plans if cell_distance(p["attack_cell"], foe_cell) > 1.5), None)
    if far is not None:
        assert slots_v3.attackable_v3(slots, c, slots.plans.index(far), b_idx, 0) is False


#--- 3. decode/label_of round-trip -------------------------------------------
def test_decode_produces_ordered_turn_and_label_of_recovers_it():
    ctx = _adjacent()
    slots, c, _o = _slots(ctx)
    b_idx = next(i for i, t in enumerate(slots.targets) if t["id"] == "B")
    # найдём план «атаковать с соседней клетки, затем уйти»
    plan = next(p for p in slots.plans if p["attack_cell"] == (0, 5) and p["end_cell"] != (0, 5))
    plan_i = slots.plans.index(plan)
    label = {"plan": plan_i, "target": b_idx, "weapon": 0}
    actions = slots_v3.decode(slots, label)
    kinds = [a.action for a in actions]
    assert kinds.index("use") < max(i for i, k in enumerate(kinds) if k == "move")  # есть уход после удара
    assert kinds.index("use") > min(i for i, k in enumerate(kinds) if k == "move") or plan["costIn"] == 0
    assert slots_v3.label_of(c, slots, actions) == label     # восстанавливаем ровно тот же план


#--- 5. все пять тактических последовательностей представимы ----------------
@pytest.mark.parametrize("name,dirs_in,attack,dirs_out", [
    ("move_and_attack", ["right"], True, []),                 # подойти вплотную, ударить
    ("attack_then_retreat", [], True, ["left", "left"]),      # с места и отойти
    ("out_shoot_back", ["right"], True, ["left"]),            # выйти, ударить, вернуться
    ("attack_and_gap", [], True, ["left"]),                   # ударить и увеличить дистанцию
    ("move_no_attack", ["left"], False, []),                  # переместиться без атаки
])
def test_sequences_representable_and_executable(name, dirs_in, attack, dirs_out):
    ctx = _adjacent()
    origin = ctx.src_cell                                    # (0,5); враг B в (0,6)
    foe = ctx.cell_of(ctx.token("B"))
    sim = Simulation.of(ctx)
    acts = [target_action("B")] + [move_action(d) for d in dirs_in]
    if attack:
        acts.append(use_action("sword"))
    acts += [move_action(d) for d in dirs_out]
    after = sim.apply_actor_seq("A", acts)
    assert after.cells["A"] == apply_moves(origin, dirs_in + dirs_out)   # порядок движений соблюдён
    cell_at_use = apply_moves(origin, dirs_in)               # где актёр в момент удара
    expected_hit = attack and within_reach(cell_at_use, foe, 1.0)
    assert (after.hp["B"] < 20) is expected_hit


#--- 7. bump схемы: dims3 отличается, в2-веса несовместимы ------------------
def test_dims3_differs_from_v2_schema():
    assert spec3.SCHEMA == 3 and spec.SCHEMA == 2
    d2, d3 = spec.dims(), spec3.dims3()
    assert d3["schema"] == 3
    assert d3["cell_feat"] == len(spec3.CELL3_FEATURES)
    assert d3["cells"] == spec3.K_MOVEPLAN + 1
    assert (d3["cells"], d3["cell_feat"]) != (d2["cells"], d2["cell_feat"])
