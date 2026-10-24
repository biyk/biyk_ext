# tests/test_arent_encode_v3.py — наблюдение схемы 3: форма, размерности, метка move-plan.
#
# Проверка идёт по НАСТОЯЩУЮ цепочку разметки (как dataset.sample_one): независимая командная
# сцена -> teacher.label -> observe -> slots_v3.build -> label_of -> encode_v3.encode. Утверждаем
# контракт образца schema=3: те же ключи, что у v2; ширина/глубина головы cells = spec3;
# состояние/цели/оружие = ширины v2; метка = {plan,target,weapon}, plan указывает на реальный слот.
import pytest

from arent import dataset, encode, encode_v3, slots as slots_v2, slots_v3, spec, spec3
from arent.observe import observe
from arent.teacher import pinned
from arent.teachers import get_teacher


def _labeled_pool(n=8, seed=7):
    pool, _ = dataset.scenario_sources(n, seed)
    assert pool, "генератор обязан выдать хотя бы одну боеспособную командную сцену"
    teacher = get_teacher("greedy", rounds=1, time_limit_sec=0.5)
    with pinned(rounds=1, time_limit_sec=0.5):
        for name, payload in pool:
            labeled = teacher.label(payload)
            ctx = labeled.ctx
            if not ctx.weapons or not ctx.hostile_targets() or not labeled.actions:
                continue
            obs = observe(ctx, None, ctx.src_id)
            slots = slots_v3.build(ctx, obs)
            slots_v3.ensure_plan(slots, ctx, labeled.actions)
            label = slots_v3.label_of(ctx, slots, labeled.actions)
            if slots.plans and label is not None:
                return ctx, obs, slots, label
    pytest.skip("ни одна сцена не дала корректную разметку move-plan")


def test_encode_v3_sample_matches_v2_keys_with_plan_head():
    ctx, obs, slots, label = _labeled_pool()
    sample = encode_v3.encode(ctx, obs, slots, label, value=1.0, meta={"arena": "gen_x"})
    # контракт: те же ключи, что у образца схемы 2
    v2 = encode.observation(ctx, obs, slots_v2.build(ctx, obs))
    assert set(sample) == {"schema", "feat_version", "state", "cells", "targets", "weapons",
                           "mask", "legal", "y", "value", "meta"}
    # ЭТАП 6 (1.2): пример несёт явную версию признаков головы move-plan
    assert sample["feat_version"] == spec3.FEATURES_VERSION == 2
    assert sample["feat_version"] == spec3.dims3()["feat_version"]
    # legal — точная совместная маска A(s) [n_plans][targets][weapons], снятая при сборе примера
    assert len(sample["legal"]) == spec3.K_MOVEPLAN + 1
    assert len(sample["legal"][0]) == len(sample["mask"]["targets"])
    assert len(sample["legal"][0][0]) == len(sample["mask"]["weapons"])
    assert set(sample["mask"]) == set(v2["mask"])
    assert sample["schema"] == spec3.SCHEMA == 3
    assert sample["meta"]["schema"] == 3
    # голова cells = перемещения-планы: глубина K_MOVEPLAN+1, ширина = len(CELL3_FEATURES)
    assert len(sample["cells"]) == spec3.K_MOVEPLAN + 1
    assert all(len(v) == len(spec3.CELL3_FEATURES) for v in sample["cells"])
    assert len(sample["mask"]["cells"]) == spec3.K_MOVEPLAN + 1
    assert sum(sample["mask"]["cells"]) == slots.n_plans       # ровно n_plans активных слотов
    # состояние/цели/оружие — ширины схемы 2 (не изменились)
    assert len(sample["state"]) == len(v2["state"])
    assert sample["targets"] == v2["targets"]                  # цели кодируются как в v2
    assert sample["weapons"] == v2["weapons"]                  # оружие кодируется как в v2
    # метка: plan/target/weapon, plan указывает на реальный активный слот
    assert set(sample["y"]) == {"plan", "target", "weapon"}
    assert 0 <= sample["y"]["plan"] < slots.n_plans
    assert sample["value"] == encode._r(1.0 / spec.VALUE_SCALE)


def test_encode_v3_plan_label_round_trips_to_executable_sequence():
    """Метка y[plan] -> decode обязан собрать последовательность, которую sim применит по порядку."""
    from planner.geometry import apply_moves
    from planner.sim import Simulation
    ctx, obs, slots, label = _labeled_pool()
    seq = slots_v3.decode(slots, label)
    sim = Simulation.of(ctx)
    origin = ctx.src_cell
    dirs = [a.conf["direction"] for a in seq if a.action == "move"]
    after = sim.apply_actor_seq(ctx.src_id, seq)
    # финальная клетка = сумма смещений плана (инвариант представимости move-plan'а)
    assert after.cells[ctx.src_id] == apply_moves(origin, dirs)
    # перемещений не больше бюджета хода
    assert len(dirs) <= ctx.speed_steps


def test_encode_v3_rejects_v2_dims_via_schema_guard():
    """v3-размерности отличаются от v2 -> старые v2-веса несовместимы (проверка на dims)."""
    d2, d3 = spec.dims(), spec3.dims3()
    assert spec.SCHEMA == 2 and d3["schema"] == 3
    assert (d3["cells"], d3["cell_feat"]) != (d2["cells"], d2["cell_feat"])
