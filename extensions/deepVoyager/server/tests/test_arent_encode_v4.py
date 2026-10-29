# tests/test_arent_encode_v4.py — наблюдение схемы 4: хвост ресурсов, флаги оружия, Ao-признаки.
#
# Контракт: v4 = v3 (те же ключи sample) + экономика действий/Ao. Утверждаем:
#   state = v2/v3-состояние (побитовый префикс!) + resource_tail (последние 3 = 1.0 по умолчанию);
#   cells = ширина CELL4_FEATURES (23), глубина K_MOVEPLAN+1, хвостовые 2 колонки = provokesAo/aoRisk;
#   weapons = ширина WEAPON_FEATURES4 (14): старые 11 колонок побитово + [isAction,isBonus,isReaction];
#   targets = ровно как v2; schema=4, feat_version=spec4; legal — маска A(s) как v3.
# Плюс smoke: PolyFightEnv(schema=4).reset даёт obs ширины dims4 и один шаг проходит (ресурсы актёра
# откачены, состояние шьётся). Строим по настоящей цепочке teacher -> observe -> slots_v3 -> encode_v4.
import pytest

from arent import dataset, encode, encode_v4, slots_v3, spec, spec4
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


def test_encode_v4_state_tail_and_prefix_parity():
    ctx, obs, slots, label = _labeled_pool()
    v2_state = encode.state(obs)
    sample = encode_v4.encode(ctx, obs, slots, label, value=1.0, meta={"arena": "gen_x"})
    assert sample["schema"] == spec4.SCHEMA == 4
    assert sample["feat_version"] == spec4.FEATURES_VERSION
    # побитовый префикс: старые колонки state стоят на своих местах (перенос copy[:, :old]+pad)
    assert sample["state"][:len(v2_state)] == v2_state
    # хвост ресурсов (по умолчанию всё доступно -> 1.0), порядок = RESOURCE_FEATURES
    tail = sample["state"][len(v2_state):]
    assert tail == [1.0, 1.0, 1.0]
    assert len(sample["state"]) == spec4.dims4()["state"] == len(v2_state) + len(spec4.RESOURCE_FEATURES)


def test_encode_v4_head_widths_cells_and_weapons():
    ctx, obs, slots, label = _labeled_pool()
    v2_weapons = encode.weapon_vectors(obs, slots)   # v2-оружие: префикс для сравнения
    v2_targets = encode.target_vectors(obs, slots)   # v2-цели: кодируются идентично
    sample = encode_v4.observation(ctx, obs, slots)
    # cells: глубина move-plan, ширина CELL4_FEATURES (= CELL3 + 2 Ao-колонки)
    assert len(sample["cells"]) == spec4.K_MOVEPLAN + 1
    assert all(len(v) == len(spec4.CELL4_FEATURES) for v in sample["cells"])
    # weapons: ширина WEAPON_FEATURES4 (= 11 + 3 флага), первые 11 колонок — как v2
    assert all(len(v) == len(spec4.WEAPON_FEATURES4) for v in sample["weapons"])
    for v4w, v2w in zip(sample["weapons"], v2_weapons):
        assert v4w[:len(v2w)] == v2w
    # flags реального оружия: isAction=1, isBonus=0, isReaction=1 у ближнего боя (не ranged/thrown)
    w0 = sample["weapons"][0]
    base = w0[:len(spec.WEAPON_FEATURES)]
    melee = base[4] == 1.0          # 'melee' колонка = 1 когда не ranged
    assert w0[-3:] == [1.0, 0.0, 1.0 if melee else 0.0]
    # targets — ровно как в v2
    assert sample["targets"] == v2_targets


def test_encode_v4_pad_slot_has_zero_ao_features():
    ctx, obs, slots, label = _labeled_pool()
    sample = encode_v4.observation(ctx, obs, slots)
    pad = sample["cells"][-1]                       # последний (пустой) слот — нули, Ao-хвост 0
    assert pad[-2:] == [0.0, 0.0]
    # provokesAo/aoRisk в диапазоне: флаг 0/1, риск неотрицателен
    for v in sample["cells"]:
        assert v[-2] in (0.0, 1.0)
        assert v[-1] >= 0.0


def test_encode_v4_legal_mask_shape_tracks_v3():
    ctx, obs, slots, label = _labeled_pool()
    sample = encode_v4.encode(ctx, obs, slots, label, value=1.0, meta={"arena": "gen_x"})
    assert len(sample["legal"]) == spec4.K_MOVEPLAN + 1
    assert len(sample["legal"][0]) == len(sample["mask"]["targets"])
    assert len(sample["legal"][0][0]) == len(sample["mask"]["weapons"])
    assert set(sample["y"]) == {"plan", "target", "weapon"}


def test_polyenv_schema4_reset_and_step_smoke():
    from arent.polyenv import PolyFightEnv
    pool, _ = dataset.scenario_sources(8, 7)
    teacher = get_teacher("greedy", rounds=1, time_limit_sec=0.5)
    env = PolyFightEnv(rounds_cap=4, schema=spec4.SCHEMA)
    for name, payload in pool:
        with pinned(rounds=1, time_limit_sec=0.5):
            labeled = teacher.label(payload)
        if not labeled.ctx.weapons or not labeled.ctx.hostile_targets():
            continue
        obs = env.reset(payload)
        assert obs["schema"] == spec4.SCHEMA
        assert len(obs["state"]) == spec4.dims4()["state"]
        # ресурсы актёра откачены на начале хода (reset_actor_turn в _observe)
        assert obs["state"][-3:] == [1.0, 1.0, 1.0]
        # один no-attack ход обязан пройти и вернуть следующий obs той же ширины
        nxt, reward, terminated, truncated, info = env.step(
            {"plan": 0, "target": spec.K_TARGETS, "weapon": spec.K_WEAPONS})
        assert len(env.slots.plans) >= 1
        assert isinstance(reward, float)
        if nxt is not None:
            assert len(nxt["state"]) == spec4.dims4()["state"]
        return
    pytest.skip("нет боеспособной сцены для schema-4 smoke")
