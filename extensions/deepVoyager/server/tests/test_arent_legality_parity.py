# tests/test_arent_legality_parity.py — совместная легальность едина в обучении и инференсе.
#
# Атака легальна УСЛОВНО (выбранное оружие достаёт цель из выбранной клетки/плана с LOS),
# тогда как головы сети маскируются независимо. Проверка живёт в arent/legalize.py и
# обязана давать ОДИНАКОВЫЙ результат в среде обучения (FightEnv/PolyFightEnv), командной
# оценке (team_eval.fight_teams), отдаче (play.act) и одиночной метрике (evaluate.fight).
# Никакого обучения/генерации здесь нет — только прогоны фиксированных заглушек.
from arent import evaluate, legalize, play, polyenv, slots as slots_mod, slots_v3, spec
from arent import team_eval
from arent.env import FightEnv
from arent.observe import observe
from planner.action import ACTION_USE
from planner.context import BattleContext
from planner.geometry import cell_distance
from planner.sim import Simulation
from conftest import make_npc, make_scene_payload, make_wall, make_weapon

NONE = legalize.NONE_INDEX
ILLEGAL = {"cell": 0, "target": 0, "weapon": 0}          # «стоим, целимся, бьём» — может быть нелегально


class _Stub:
    """Модель-заглушка схемы 2: всегда предлагает одну и ту же тройку (cell/target/weapon)."""

    def __init__(self, label=None, name="stub"):
        self.label = dict(ILLEGAL if label is None else label)
        self.name = name

    def predict(self, sample):
        out = dict(self.label, value=0.0)
        for k in ("cell", "target", "weapon"):
            out[k + "Prob"] = 1.0
        return out


def _melee_far():
    """Герой-бойец далеко от врага: атака с места недостижима (дальность не проходит)."""
    a = make_npc("A", 0, 0, disposition=-1, hp=20, initiative=20)
    f = make_npc("F", 8 * 50, 0, disposition=1, hp=20, initiative=5)
    payload = make_scene_payload(npcs=[a, f], weapons=[make_weapon("sw", damage="1d8+2", sure_ft=5)])
    payload.update({"src": "A", "token": "F", "speed": 30})
    return payload


def _melee_adjacent():
    """Герой и враг соседствуют: та же тройка теперь легальна (дальность ближнего боя проходит)."""
    a = make_npc("A", 0, 0, disposition=-1, hp=20, initiative=20)
    f = make_npc("F", 1 * 50, 0, disposition=1, hp=20, initiative=5)
    payload = make_scene_payload(npcs=[a, f], weapons=[make_weapon("sw", damage="1d8+2", sure_ft=5)])
    payload.update({"src": "A", "token": "F", "speed": 30})
    return payload


def _wall_between():
    """Линия видимости перекрыта стеной при достаточной дальности: не-атака по правилам LOS."""
    a = make_npc("A", 0, 0, disposition=-1, hp=20, initiative=20)
    f = make_npc("F", 4 * 50, 0, disposition=1, hp=20, initiative=5)
    wall = make_wall("w", 2 * 50, 0, 2 * 50, 50, move=0, sight=1)     # между A и F, глушит обзор
    payload = make_scene_payload(npcs=[a, f], walls=[wall],
                                 weapons=[make_weapon("bow", damage="1d8", sure_ft=5, doubt_ft=200)])
    payload.update({"src": "A", "token": "F", "speed": 30})
    return payload


def _slots(payload):
    ctx = BattleContext.from_payload(payload)
    obs = observe(ctx)
    return ctx, obs, slots_mod.build(ctx, obs)


#--- 1. легальная атака остаётся без изменений -------------------------------------
def test_legal_attack_is_unchanged():
    ctx, obs, slots = _slots(_melee_adjacent())
    assert slots_mod.attackable(slots, ctx, 0, 0, 0), "сцена должна давать легную атаку"
    fixed, reason = legalize.legalize(ILLEGAL, spec.SCHEMA, slots, ctx)
    assert reason is None and fixed == ILLEGAL                        # идемпотентно


#--- 2. недостижимая цель не позволяет исполнить атаку ------------------------------
def test_unreachable_target_attack_is_dropped():
    ctx, obs, slots = _slots(_melee_far())
    assert not slots_mod.attackable(slots, ctx, 0, 0, 0)              # слишком далеко
    fixed, reason = legalize.legalize(ILLEGAL, spec.SCHEMA, slots, ctx)
    assert reason == legalize.REASON_UNREACHABLE
    assert fixed["weapon"] == NONE and fixed["cell"] == 0             # движение/прицел остались
    assert not any(a.action == ACTION_USE for a in slots_mod.decode(slots, fixed))  # атаки нет


#--- 3. несовместимые план/цель/оружие исправляются или отклоняются (v3) ------------
def test_incompatible_plan_target_weapon_corrected():
    ctx = BattleContext.from_payload(_melee_far())
    obs = observe(ctx)
    slots = slots_v3.build(ctx, obs)
    assert 0 < len(slots.plans) and slots.targets and slots.weapons
    proposal = {"plan": 0, "target": 0, "weapon": 0}
    legal = slots_v3.attackable_v3(slots, ctx, 0, 0, 0)
    fixed, reason = legalize.legalize(proposal, spec3_schema(), slots, ctx)
    if legal:
        assert reason is None and fixed == proposal                   # совместный план не трогаем
    else:
        assert reason == legalize.REASON_UNREACHABLE and fixed["weapon"] == NONE


def spec3_schema():
    from arent import spec3
    return spec3.SCHEMA


#--- 4. дальность и LOS проверяются по правилам симуляции ---------------------------
def test_los_blocks_in_range_attack():
    ctx, obs, slots = _slots(_wall_between())
    target_cell = slots.targets[0]["id"]
    hero_cell = slots.cells[0]["cell"]
    at = ctx.cell_of(ctx.token(target_cell))
    within = cell_distance(hero_cell, at) <= float(slots.weapons[0]["doubtCells"]) + 0.5
    assert within, "дальность должна проходить — блокировать должен именно LOS"
    assert not slots_mod.attackable(slots, ctx, 0, 0, 0)              # LOS перекрыт стеной
    fixed, reason = legalize.legalize(ILLEGAL, spec.SCHEMA, slots, ctx)
    assert reason == legalize.REASON_UNREACHABLE and fixed["weapon"] == NONE


def test_legalize_agrees_with_attackable_for_all_triples():
    """Единый компонент == примитив симуляции на КАЖДОЙ тройке (дальность и LOS включены)."""
    for payload in (_melee_far(), _melee_adjacent(), _wall_between()):
        ctx, obs, slots = _slots(payload)
        for ci in range(slots.n_cells):
            for ti in range(len(slots.targets)):
                for wi in range(len(slots.weapons)):
                    legal = slots_mod.attackable(slots, ctx, ci, ti, wi)
                    act = {"cell": ci, "target": ti, "weapon": wi}
                    fixed, reason = legalize.legalize(act, spec.SCHEMA, slots, ctx)
                    assert (fixed["weapon"] == wi) == legal           # оружие сохранено iff легально
                    assert (reason is None) == legal


#--- 5. действия v2 работают по прежним правилам ------------------------------------
def test_v2_env_still_legalizes_as_before():
    env = FightEnv(rounds_cap=4, schema=spec.SCHEMA)
    obs = env.reset(_melee_far())
    fixed = env.legalize(dict(ILLEGAL))
    assert fixed == {"cell": 0, "target": 0, "weapon": NONE}          # как до рефакторинга
    ctx, _o, slots = _slots(_melee_far())
    shared, _r = legalize.legalize(ILLEGAL, spec.SCHEMA, slots, ctx)
    assert fixed == shared                                            # среда и компонент совпали


#--- 6. одинаковые входные данные дают согласованный итог в обучении/оценке/play ----
def test_same_input_consistent_across_training_play_eval():
    payload = _melee_far()
    ctx, _o, slots = _slots(payload)
    shared, _r = legalize.legalize(ILLEGAL, spec.SCHEMA, slots, ctx)

    # play: недопустимое предложение сети исправлено, атака не исполнена
    res = play.act(_Stub(), payload)
    assert res["y"] == shared                                          # ровно тот же итог
    assert res["legalize"]["illegal_proposal"] and not res["legalize"]["executed"]

    # evaluate (одиночный контур): недопустимая атака не исполняется, а исполненная — с уроном
    row = evaluate.fight(_Stub(), payload, rounds=3)
    assert row["illegal_proposals"] >= 1
    assert row["zero_damage_attacks"] == 0                             # ни одной атаки всхолую

    # team-eval: кандидат с той же заглушкой не проводит ни одной атаки с нулевым уроном
    tr = team_eval.fight_teams(payload, _Stub(), _Stub({"cell": 0, "target": -1, "weapon": -1}),
                               rounds_cap=2)
    assert tr["illegal_proposals"] >= 1
    assert tr["attacks_zero_damage"] == 0


#--- 7. вызов проверки не меняет состояние боя и не наносит урона -------------------
def test_check_has_no_side_effect_on_battle():
    payload = _melee_adjacent()
    state = Simulation.of(BattleContext.from_payload(payload))
    ctx = state.context_for(state.hero_id)
    slots = slots_mod.build(ctx, observe(ctx))
    before = {uid: (u.hp, getattr(u, "damage", None)) for uid, u in state.units.items()}
    for _ in range(3):
        legalize.legalize(ILLEGAL, spec.SCHEMA, slots, ctx)
        legalize.legalize({"cell": 0, "target": 0, "weapon": 0}, spec.SCHEMA, slots, ctx)
    after = {uid: (u.hp, getattr(u, "damage", None)) for uid, u in state.units.items()}
    assert before == after                                             # бой не сдвинулся


def test_polypolyenv_uses_shared_component_for_v3():
    """PolyFightEnv v3 чинит недопустимую атаку тем же компонентом (делегирование без дубля)."""
    payload = _melee_far()
    env = polyenv.PolyFightEnv(rounds_cap=2, schema=3)
    env.reset(payload)
    ctx, _o, _s = _slots(payload)
    slots = slots_v3.build(ctx, observe(ctx))
    fixed = env.legalize({"plan": 0, "target": 0, "weapon": 0})
    shared, _r = legalize.legalize({"plan": 0, "target": 0, "weapon": 0}, 3, slots, ctx)
    assert fixed == shared
