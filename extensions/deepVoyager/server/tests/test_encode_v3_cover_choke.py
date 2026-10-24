# tests/test_encode_v3_cover_choke.py — coverLos/atChokeEnd в голове move-plan (Этап 4).
#
# cover_shoot/hold_choke представимы модели ТОЛЬКО если план-вектор несёт LOS-укрытие и
# признак узости финальной клетки. Проверяем: контракт ширины (23) и версии (3), конкретные
# значения на скелетном ctx, и сохранение permutation-invariance (признаки контентные).
import pytest

from arent import dataset, encode_v3, slots_v3, spec3
from arent.observe import observe
from arent.teachers import get_teacher
from arent.teacher import pinned
from conftest import make_npc, make_scene_payload, make_wall
from planner.context import BattleContext


def _feat(plan_vec, name):
    i = spec3.CELL3_FEATURES.index(name)
    return plan_vec[i]


def test_cell3_features_widened_with_cover_and_choke():
    assert spec3.FEATURES_VERSION == 3
    assert len(spec3.CELL3_FEATURES) == 23
    assert "coverLos" in spec3.CELL3_FEATURES and "atChokeEnd" in spec3.CELL3_FEATURES
    assert spec3.dims3()["cell_feat"] == 23 and spec3.dims3()["feat_version"] == 3


def test_plan_vector_encodes_cover_and_choke():
    # вертикальная стена x=300 с проёмом на row5: (5,5) узость; (0,0) под укрытием от врага (0,8)
    walls = []
    for r in range(10):
        if r != 5:
            walls.append(make_wall(f"v{r}", 300, r * 50, 300, (r + 1) * 50, move=1, sight=1))
    npcs = [make_npc("A", 0, 0, disposition=-1, hp=30),
            make_npc("B", 400, 0, disposition=1, hp=30)]      # клетка (0,8)
    payload = make_scene_payload(walls=walls, npcs=npcs, token="B")
    payload.update({"src": "A", "speed": 30, "weapons": [{"id": "sword", "name": "sword",
                                                          "damage": "1d6", "bonus": 0,
                                                          "sureFt": 5, "doubtFt": 5}]})
    ctx = BattleContext.from_payload(payload)
    obs = observe(ctx)
    from planner.los import sight_segments
    segs = sight_segments(ctx)
    plan_cov = {"attack_cell": (0, 0), "end_cell": (0, 0), "adx": 0, "ady": 0, "adist": 0,
                "edx": 0, "edy": 0, "edist": 0, "costIn": 0, "costOut": 0, "costTotal": 0,
                "retreatToOrigin": False}
    vec = encode_v3.plan_vector(ctx, obs, plan_cov, 0, 2, segs)
    assert len(vec) == 23
    assert _feat(vec, "coverLos") == 1.0        # (0,0) за стеной x=300 от врага (0,8)
    assert _feat(vec, "atChokeEnd") == 0.0      # (0,0) не узость
    plan_choke = dict(plan_cov, end_cell=(5, 5))
    vec2 = encode_v3.plan_vector(ctx, obs, plan_choke, 0, 2, segs)
    assert _feat(vec2, "atChokeEnd") == 1.0     # (5,5) — дверь единственного прохода


def test_encode_sample_head_depth_and_width():
    # сквозной контракт: real scene -> encode, все векторы cells ширины 23
    pool, _ = dataset.scenario_sources(6, 7)
    teacher = get_teacher("greedy", rounds=1, time_limit_sec=0.5)
    with pinned(rounds=1, time_limit_sec=0.5):
        for name, payload in pool:
            labeled = teacher.label(payload)
            ctx = labeled.ctx
            if not ctx.weapons or not ctx.hostile_targets() or not labeled.actions:
                continue
            obs = observe(ctx, None, ctx.src_id)
            slots = slots_v3.build(ctx, obs)
            label = slots_v3.label_of(ctx, slots, labeled.actions)
            if not slots.plans or label is None:
                continue
            sample = encode_v3.encode(ctx, obs, slots, label, value=1.0, meta={"arena": name})
            assert sample["feat_version"] == 3
            assert all(len(v) == 23 for v in sample["cells"])
            return
    pytest.skip("ни одна сцена не дала разметку move-plan")
