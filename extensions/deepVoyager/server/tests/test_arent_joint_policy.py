# tests/test_arent_joint_policy.py — этап 3: совместный выбор действий политикой и logπ.
#
# Проверяем МАТЕМАТИКУ политики (не только постфактум-починку legalize):
#  • выбор идёт из нормированного произведения голов по множеству совместно допустимых
#    троек (arent/joint.py), поэтому каждое выбранное действие уже легально и legalize —
#    тождество;
#  • logπ в rollout и на PPO-обновлении берётся от ОДНОГО и того же распределения;
#  • «не атаковать» представлено ровно одним вариантом на позицию (нет дублей);
#  • доказано: старое «произведение независимых голов» НЕ совпадает с вероятностью
#    исполненного действия, когда proposal починен (pushforward через legalize).
# Обучение НЕ запускаем: фиксированные веса (случайная инициализация) + синтетические сцены.
import math
import random

import pytest

from arent import backend, joint, net, polyenv, rl_state, slots as slots_mod, slots_v3, spec, spec3
from arent.env import FightEnv
from arent.observe import observe
from arent.rollout import RlConfig, collect
from arent.torch_rl import PPOAgent, joint_logp
from planner.context import BattleContext
from conftest import make_npc, make_scene_payload, make_wall, make_weapon

torch = pytest.importorskip("torch")

NONE_W = joint.NONE_WEAPON
NONE_T = joint.NONE_TARGET


# --------------------------------------------------------------------------- сцены/сборка
def _melee_adjacent():
    a = make_npc("A", 0, 0, disposition=-1, hp=20, initiative=20)
    f = make_npc("F", 1 * 50, 0, disposition=1, hp=20, initiative=5)
    p = make_scene_payload(npcs=[a, f], weapons=[make_weapon("sw", damage="1d8+2", sure_ft=5)])
    p.update({"src": "A", "token": "F", "speed": 30})
    return p


def _melee_far():
    a = make_npc("A", 0, 0, disposition=-1, hp=20, initiative=20)
    f = make_npc("F", 8 * 50, 0, disposition=1, hp=20, initiative=5)
    p = make_scene_payload(npcs=[a, f], weapons=[make_weapon("sw", damage="1d8+2", sure_ft=5)])
    p.update({"src": "A", "token": "F", "speed": 30})
    return p


def _wall_between():
    a = make_npc("A", 0, 0, disposition=-1, hp=20, initiative=20)
    f = make_npc("F", 4 * 50, 0, disposition=1, hp=20, initiative=5)
    wall = make_wall("w", 2 * 50, 0, 2 * 50, 50, move=0, sight=1)
    p = make_scene_payload(npcs=[a, f], walls=[wall],
                           weapons=[make_weapon("bow", damage="1d8", sure_ft=5, doubt_ft=200)])
    p.update({"src": "A", "token": "F", "speed": 30})
    return p


def _v2_samples(n=6):
    e = FightEnv(rounds_cap=8)
    out = [e.reset(_melee_far())]
    while len(out) < n:
        nxt, _r, term, trunc, _i = e.step({"cell": 0, "target": -1, "weapon": -1})
        if term or trunc:
            nxt = e.reset(_melee_adjacent())
        out.append(nxt)
    return out[:n]


def _v3_samples(n=4):
    e = polyenv.PolyFightEnv(rounds_cap=6, schema=spec3.SCHEMA)
    out = [e.reset(_melee_far())]
    while len(out) < n:
        nxt, _r, term, trunc, _i = e.step({"plan": 0, "target": -1, "weapon": -1})
        if term or trunc:
            nxt = e.reset(_melee_adjacent())
        out.append(nxt)
    return out[:n]


def _agent(schema=2, seed=3):
    cfg = net.Config(schema=schema, hidden=16, head=4, seed=seed)
    return PPOAgent(backend.build(cfg, kind="torch", device="cpu"), ppo_epochs=2, minibatch=4)


# --------------------------------------------------------------------------- справочное распределение
def _legal_entries(legal):
    for p, row in enumerate(legal):
        for t, col in enumerate(row):
            for w, val in enumerate(col):
                if val:
                    yield p, t, w


def _ref_logZ(table, legal):
    vals = [table["cells"][p] + table["targets"][t] + table["weapons"][w]
            for p, t, w in _legal_entries(legal)]
    assert vals, "допустимое множество не может быть пустым (есть no-attack на каждую клетку)"
    m = max(vals)
    return m + math.log(sum(math.exp(v - m) for v in vals))


# --------------------------------------------------------------------------- 1. выбор всегда легален
@pytest.mark.parametrize("schema", [2, 3])
def test_every_sampled_action_is_jointly_legal(schema):
    """Выбор из совместного множества: каждая тройка легальна, а legalize В ТОМ ЖЕ
    состоянии (те же слоты, что породили s['legal']) — тождество, причина правки не гасится."""
    agent = _agent(schema=schema)
    torch.manual_seed(0)
    mk = (lambda: FightEnv(rounds_cap=4, schema=2)) if schema == 2 \
        else (lambda: polyenv.PolyFightEnv(rounds_cap=4, schema=3))
    for scene in (_melee_far(), _melee_adjacent(), _wall_between()):
        e = mk()
        s = e.reset(scene)                          # e.slots соответствует s['legal']
        for _ in range(12):
            a = agent.act(s)["action"]
            assert joint.is_jointly_legal(a, s["legal"], schema)
            fixed = e.legalize(dict(a))             # то же состояние -> правки нет
            assert fixed == a
            assert e._last_reason is None


# --------------------------------------------------------------------------- 2/4. logπ и нормировка
@pytest.mark.parametrize("schema", [2, 3])
def test_sampled_logp_matches_reference_distribution(schema):
    agent = _agent(schema=schema)
    torch.manual_seed(1)
    samples = _v2_samples(4) if schema == 2 else _v3_samples(4)
    yk = agent.ykey
    for s in samples:
        out = agent.act(s)
        a = out["action"]
        logZ = _ref_logZ(out["logp_table"], s["legal"])
        raw = (out["logp_table"]["cells"][a[yk["cells"]]]
               + out["logp_table"]["targets"][a[yk["targets"]]]
               + out["logp_table"]["weapons"][a[yk["weapons"]]])
        # act logπ == sum по голоам минус нормировка (то же, что joint_logp с logZ)
        assert out["logp"] == pytest.approx(raw - logZ, abs=1e-4)
        assert joint_logp(out["logp_table"], a, yk, out["logZ"]) == pytest.approx(out["logp"], abs=1e-5)
        assert out["logZ"] == pytest.approx(logZ, abs=1e-4)
        # вероятности допустимых вариантов нормированы: Σ exp(logπ) == 1
        total = sum(math.exp(out["logp_table"]["cells"][p] + out["logp_table"]["targets"][t]
                             + out["logp_table"]["weapons"][w] - logZ)
                    for p, t, w in _legal_entries(s["legal"]))
        assert total == pytest.approx(1.0, abs=1e-4)


# --------------------------------------------------------------------------- 3. rollout == update
def test_rollout_and_update_use_same_logp():
    agent = _agent(schema=2)
    torch.manual_seed(2)
    s = _v2_samples(1)[0]
    out = agent.act(s)
    new_logp, _ent, _v = agent._eval([s], [out["action"]])
    assert float(new_logp[0].item()) == pytest.approx(out["logp"], abs=1e-4)


# --------------------------------------------------------------------------- 5. нет дублей no-attack
def test_no_attack_is_canonical_single_option():
    for s in _v2_samples(3):
        legal = s["legal"]
        seen_real = False
        for row in legal:
            if not any(any(col) for col in row):
                continue                                # pad-позиция (недостижимая клетка): ряд пуст
            seen_real = True
            # ровно один канонический «не атаковать» (NONE, NONE) для позиции
            assert row[NONE_T][NONE_W] == 1
            # нет неканонических no-attack: атака без оружия или оружие без цели запрещены
            for t in range(NONE_T):
                assert row[t][NONE_W] == 0
            for w in range(NONE_W):
                assert row[NONE_T][w] == 0
        assert seen_real, "хотя бы одна реальная позиция должна присутствовать"


def test_no_attack_mass_is_single_term():
    """Вероятность «не атаковать» = Σ_p πc(p)·πt(NONE)·πw(NONE)/Z — один член на клетку."""
    agent = _agent(schema=2)
    torch.manual_seed(3)
    s = _v2_samples(1)[0]
    out = agent.act(s)
    table, legal = out["logp_table"], s["legal"]
    logZ = _ref_logZ(table, legal)
    members = [(p, t, w) for p, t, w in _legal_entries(legal) if t == NONE_T and w == NONE_W]
    noattack = sum(math.exp(table["cells"][p] + table["targets"][NONE_T] + table["weapons"][NONE_W]
                            - logZ) for p, _t, _w in members)
    assert 0.0 <= noattack <= 1.0
    # «не атаковать» — ровно один член на реальную позицию: дублей no-attack нет
    n_positions = sum(1 for row in legal if any(any(col) for col in row))
    assert len(members) == n_positions
    # сумма Members == вероятность no-attack, посчитанная напрямую из logπ act() как события
    direct = sum(math.exp(table["cells"][p] + table["targets"][NONE_T] + table["weapons"][NONE_W] - logZ)
                 for p, _t, _w in members)
    assert noattack == pytest.approx(direct, abs=1e-12)


# --------------------------------------------------------------------------- 6. legalize идемпотентен
def test_legalize_identity_on_legal_action():
    """Действие из совместного множества проходит защитный legalize без изменений."""
    agent = _agent(schema=2)
    torch.manual_seed(5)
    e = FightEnv(rounds_cap=4, schema=spec.SCHEMA)
    for scene in (_melee_far(), _melee_adjacent(), _wall_between()):
        s = e.reset(scene)
        for _ in range(6):
            a = agent.act(s)["action"]
            assert joint.is_jointly_legal(a, s["legal"], spec.SCHEMA)
            assert e.legalize(dict(a)) == a and e._last_reason is None


# --------------------------------------------------------------------------- 7. смена стороны/контроллера
def test_self_play_both_sides_actions_are_legal():
    """Self-play по обеим командам (polyactor): каждая исполненная тройка легальна, правок нет."""
    torch.manual_seed(4)
    agent = _agent(schema=2)
    rcfg = RlConfig(rollout_steps=24, rounds_cap=3, seed=4, use_team_reward=True)
    buf = collect(agent, [("a", _melee_far()), ("b", _melee_adjacent())], rcfg, random.Random(4))
    assert len(buf) == 24
    for row in buf:
        assert joint.is_jointly_legal(row["action"], row["sample"]["legal"], spec.SCHEMA)


# --------------------------------------------------------------------------- 1-part-b. v2 не сломана
def test_schema_v2_action_space_unchanged():
    """Маска клеток не даёт NONE; атака v2 проходит по прежним правилам attackable."""
    e = FightEnv(rounds_cap=4, schema=spec.SCHEMA)
    s = e.reset(_melee_far())
    assert s["mask"]["cells"][spec.K_CELLS] == 0                     # клетки: NONE недоступен
    ctx, obs, slots = _ctx_slots(_melee_far())
    assert not slots_mod.attackable(slots, ctx, 0, 0, 0)             # далеко -> нелегально
    legal = joint.legal_mask(slots, ctx, spec.SCHEMA)
    for _p, t, w in _legal_entries(legal):                           # ни одной нелегальной атаки в наборе
        if t < len(slots.targets) and w < len(slots.weapons):
            assert slots_mod.attackable(slots, ctx, _p, t, w)


def test_v3_action_space_uses_attack_cell():
    ctx = BattleContext.from_payload(_melee_far())
    obs = observe(ctx)
    slots = slots_v3.build(ctx, obs)
    legal = joint.legal_mask(slots, ctx, spec3.SCHEMA)
    for p, t, w in _legal_entries(legal):
        if t < len(slots.targets) and w < len(slots.weapons):
            assert slots_v3.attackable_v3(slots, ctx, p, t, w)


def _ctx_slots(payload):
    ctx = BattleContext.from_payload(payload)
    obs = observe(ctx)
    return ctx, obs, slots_mod.build(ctx, obs)


# --------------------------------------------------------------------------- ПРОВЕРКА теории (Part 1)
def test_old_product_logp_differs_from_pushforward_when_corrected():
    """Если proposal недопустим и legalized в NONE, то log «произведения независимых голов»
    НЕ равен вероятности ИСПОЛНИТЬ (c,t,NONE) в законе «сэмплировать-и-починить» (pushforward)."""
    ctx, _obs, slots = _ctx_slots(_melee_far())
    # искусственные вероятности голов: оружие 0 (нелегальное издалека) с весом 0.6, NONE 0.4
    wp = [0.6, 0.4]                                                   # P(weapon)= [w0, NONE]
    assert len(slots.weapons) == 1
    tp = [1.0]                                                        # единственная цель
    cp = [1.0]                                                        # фиксируем клетку 0
    lwp = [math.log(x) for x in wp]
    ltp = [math.log(tp[0]), 0.0]                                      # индекс NONE_T=K_TARGETS
    lcp = [math.log(cp[0]), 0.0]
    # true pushforward P(исполнить NONE | c,t) = πw(NONE) + Σ_{недопустимых w} πw(w)
    illegal_w = [w for w in range(len(slots.weapons))
                 if not slots_mod.attackable(slots, ctx, 0, 0, w)]
    pushforward = wp[len(slots.weapons)] + sum(wp[w] for w in illegal_w)   # NONE = last
    old_product = wp[len(slots.weapons)]                              # joint_logp берёт только NONE
    assert illegal_w, "в сцене «далеко» должно быть нелегальное оружие"
    assert pushforward > old_product + 1e-9                           # СТАРЫЙ logπ занижен на мёртвую массу


# --------------------------------------------------------------------------- Part 3: версия семантики
def test_current_resume_roundtrip_still_works(tmp_path):
    """Свежий ppo_state несёт текущую семантику -> побитовое resume проходит (v2-контракт жив)."""
    cfg = net.Config(hidden=16, head=4, seed=7)
    policy = backend.build(cfg, kind="torch", device="cpu")
    path = str(tmp_path / "ppo_state.pt")
    rl_state.save(path, policy, RlConfig(), cfg, 5, "sha", None)
    restored = backend.build(cfg, kind="torch", device="cpu")
    info = rl_state.load(path, restored, cfg)
    assert info["iteration"] == 5


def test_resume_rejects_old_policy_semantics(tmp_path):
    """Старый ppo_state (семантика 1) нельзя продолжать PPO побитово: оптимизатор несовместим."""
    cfg = net.Config(hidden=16, head=4, seed=7)
    policy = backend.build(cfg, kind="torch", device="cpu")
    path = str(tmp_path / "ppo_state.pt")
    rl_state.save(path, policy, RlConfig(), cfg, 5, "sha", None)
    state = torch.load(path, map_location="cpu", weights_only=False)
    state["policy_semantics"] = joint.POLICY_SEMANTICS - 1            # имитируем старый контракт
    torch.save(state, path)
    with pytest.raises(ValueError, match="семантика политики"):
        rl_state.load(path, backend.build(cfg, kind="torch", device="cpu"), cfg)


def test_old_weights_still_loadable_as_warm_init(tmp_path):
    """Несовместимость касается только resume-оптимизатора: веса model.json грузятся как/init."""
    cfg = net.Config(hidden=16, head=4, seed=7)
    policy = backend.build(cfg, kind="torch", device="cpu")
    path = str(tmp_path / "model.json")
    net.save(policy, path, metrics={"which": "stage3"})               # формат weights не менялся
    reloaded = backend.load_policy(path, kind="torch")
    assert reloaded.params["trunk1"][0][0] == policy.params["trunk1"][0][0]
