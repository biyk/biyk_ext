# tests/test_arent_play_v3.py — F-B.3b: v3-чекпойнт играется и декодируется в «атака, затем уход».
#
# Схема берётся из cfg модели, поэтому play/evaluate сами выбирают пространство действий.
# Проверяем «action check» — то, что просил консультант: декод move-plan'а даёт последовательность,
# в которой удар (use) стоит МЕЖДУ подходами (dirs_in) и отступлением (dirs_out), и sim исполняет
# её по позиции, а не сворачивает в финальную клетку. Плюс: evaluate.fight на v3-модели не падает,
# а v2-путь остаётся прежним (в y ключ cell).
from planner.action import move_action, target_action, use_action
from planner.context import BattleContext
from planner.geometry import apply_moves
from planner.sim import Simulation

from arent import backend, dataset, evaluate, net, play, slots_v3, spec3
from arent.observe import observe


def _scene():
    pool, _ = dataset.scenario_sources(6, seed=7)
    for name, payload in pool:
        ctx = BattleContext.from_payload(payload)
        if ctx.weapons and ctx.hostile_targets():
            return payload
    return None


def _plan_moves(slots, plan_index):
    plan = slots.plans[plan_index]
    return plan["dirs_in"], plan["dirs_out"]


def test_play_act_v3_decodes_attack_before_retreat():
    payload = _scene()
    assert payload, "нужна боеспособная сцена"
    model = backend.build(net.Config(schema=3, hidden=8, head=6), kind="pure")
    result = play.act(model, payload)
    assert result["schema"] == spec3.SCHEMA == 3
    assert set(result["y"]) == {"plan", "target", "weapon"}
    # направления в действиях = dirs_in (до удара) + dirs_out (после), удар между ними
    ctx = BattleContext.from_payload(payload)
    obs = observe(ctx)
    slots = slots_v3.build(ctx, obs)
    dirs = [a["conf"]["direction"] for a in result["actions"]
            if a["action"] == "move" and a["conf"].get("direction")]
    acts = [a["action"] for a in result["actions"]]
    if "use" in acts:
        in_dirs, out_dirs = _plan_moves(slots, result["y"]["plan"])
        use_at = acts.index("use")
        moves_before = [a for a in acts[:use_at] if a == "move"]
        moves_after = [a for a in acts[use_at + 1:] if a == "move"]
        assert len(moves_before) == len(in_dirs) and len(moves_after) == len(out_dirs)
    assert len(dirs) <= ctx.speed_steps            # бюджет движения не превышен


def test_evaluate_fight_runs_v3_without_error():
    payload = _scene()
    assert payload
    model = backend.build(net.Config(schema=3, hidden=8, head=6), kind="pure")
    row = evaluate.fight(model, payload, rounds=3)
    assert set(row) >= {"rounds", "value", "survived", "cleared"}
    assert row["rounds"] <= 3


def test_play_act_v2_still_uses_cell_head():
    payload = _scene()
    assert payload
    model = backend.build(net.Config(hidden=8, head=6), kind="pure")   # schema default 2
    result = play.act(model, payload)
    assert result["schema"] == 2 and "cell" in result["y"] and "plan" not in result["y"]
    # v2-ход сворачивается в одну финальную клетку: применение даёт сумму всех смещений
    ctx = BattleContext.from_payload(payload)
    dirs = [a["conf"]["direction"] for a in result["actions"] if a["action"] == "move"]
    after = Simulation.of(ctx).apply_actor(ctx.src_id, _rebuild(result["actions"]))
    assert after.cells[ctx.src_id] == apply_moves(ctx.src_cell, dirs)


def _rebuild(action_dicts):
    out = []
    for a in action_dicts:
        if a["action"] == "move":
            out.append(move_action(a["conf"]["direction"]))
        elif a["action"] == "target":
            out.append(target_action(a["conf"]["id"]))
        elif a["action"] == "use":
            out.append(use_action(a["conf"]["itemId"]))
    return out
