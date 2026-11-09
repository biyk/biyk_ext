# tests/test_arent_train_v5.py — Этап 7-подготовка: СКВОЗНОЙ v5-путь обучения (не запуск тренировки).
#
# Maneuver-голова (схема 5) вшита в dataset/PPO/BC/env; этот тест ДОКАЗЫВАЕТ, что путь реально
# обучаем end-to-end, при этом НИКАКИХ тренировочных циклов не запускаем (Q2 «готовить, не запускать»):
#   1) СРЕДА: PolyFightEnv(schema=5) на полигоне 1-4 vs 1-4 несёт maneuver-слоты, 4D-маску A(s)
#      [P][T][W][M] и исполняет ход Dodge (у актёра поднимается dodging=True, удара нет);
#   2) BC: TorchPolicy(schema=5).step_batch по v5-выборке (teacher-атаки + синтетический позитивный
#      манёвр) даёт КОНЕЧНЫЙ loss/value и CE по maneuver-голове — градиент течёт в 4-ю голову
#      (прежний NotImplementedError снят);
#   3) PPO: PPOAgent(schema=5).act выдаёт действие с ключом maneuver, легальное в 4D A(s);
#      _eval пересчитывает logπ той же четвёрки (rollout==update); update доходит до конечного отчёта.
# Никаких изменений весов candidate/боевых чекпойнтов: фиксированная инициализация + CPU.
import math

import pytest

from arent import backend, dataset, joint, net, polyenv, scenarios, spec, spec5
from arent.battlecast import BattlecastTeacher
from arent.scenario_units import MANEUVER_ITEMS
from arent.teacher import Labeled
from arent.team_eval import ModelController
from arent.torch_rl import PPOAgent
from playground import arena
from planner.action import use_action
from planner.context import BattleContext
from planner.sim import Simulation

torch = pytest.importorskip("torch")


# --------------------------------------------------------------------------- полигон 1-N vs 1-N (манёвры розданы)
def _stage43_payloads(n: int = 4, seed: int = 2026):
    """[(name, payload)] из canon-полигона stage43: каждому бойцу розданы 3 манёвра."""
    out = []
    for name, raw, _params in scenarios.generate_stage43_canon(n, seed=seed):
        out.append((name, arena.build_payload(raw, name)))
    return out


# --------------------------------------------------------------------------- 1. СРЕДА v5
def test_env_v5_carries_maneuver_slots_and_4d_mask():
    env = polyenv.PolyFightEnv(rounds_cap=6, schema=spec5.SCHEMA)
    _name, payload = _stage43_payloads()[0]
    s = env.reset(payload)
    # 4-я голова в слотах текущего актёра и в observation-примере
    assert len(env.slots.maneuvers) == spec5.K_MANEUVERS
    assert tuple(m["kind"] for m in env.slots.maneuvers) == spec5.MANEUVER_KINDS
    assert "maneuvers" in s and "maneuvers" in s["mask"]
    assert len(s["maneuvers"]) == spec5.dims5()["maneuvers"] == spec5.K_MANEUVERS + 1
    assert len(s["maneuvers"][0]) == spec5.dims5()["maneuver_feat"]
    # legal — 4D A(s): [P][T][W][M]; измерение maneuvers = K_MANEUVERS + 1 (NONE последним)
    m_len = spec5.dims5()["maneuvers"]
    assert len(s["legal"][0][0][0]) == m_len


def test_env_v5_dodge_step_executes_use_and_sets_dodging():
    env = polyenv.PolyFightEnv(rounds_cap=6, schema=spec5.SCHEMA)
    _name, payload = _stage43_payloads()[0]
    s = env.reset(payload)
    actor = env.actor
    dodge_i = spec5.MANEUVER_KINDS.index("dodge")
    assert dodge_i < len(env.slots.maneuvers)
    action = {"plan": 0, "target": spec.NONE_SLOT, "weapon": spec.NONE_SLOT, "maneuver": dodge_i}
    # действие легально в 4D-маске (манёвр взаимоисключает атаку: цель/оружие NONE)
    assert joint.is_jointly_legal_v5(action, s["legal"])
    _obs, _r, _term, _trunc, info = env.step(action)
    assert info["actor"] == actor
    assert info["legalize_reason"] is None                       # легальное — правки нет
    assert env.state.units[actor].dodging is True                # Уклонение исполнилось
    assert env.state.units[actor].action < 1                     # действие списано, удара не было


# --------------------------------------------------------------------------- 2. BC v5 (4-я голова обучается)
def _v5_bc_batch(n: int = 3):
    """v5-выборка: teacher-ходы со stage43 (maneuver=NONE) + заведомо позитивный манёвр."""
    teacher = BattlecastTeacher()
    samples = []
    for name, payload in _stage43_payloads():
        ctx = BattleContext.from_payload(payload)
        order = Simulation.of(ctx, env_seed=7).initiative_order
        sample, reason = dataset.sample_one_v5(name, payload, teacher, {"arena": name}, order)
        if reason == "ok":
            samples.append(sample)
        if len(samples) >= n:
            break
    # гарантируем ненулевой обучающий сигнал maneuver-головы
    name, payload = _stage43_payloads()[0]
    ctx = BattleContext.from_payload(payload)
    dodge = next(m for m in MANEUVER_ITEMS if m["kind"] == "dodge")
    labeled = Labeled(ctx=ctx, actions=[use_action(dodge["id"])], value=0.0, score=0.0, depth=1)
    order = Simulation.of(ctx, env_seed=7).initiative_order
    positive, reason = dataset.sample_from_labeled_v5(name, labeled, {}, order)
    assert reason == "ok", reason
    assert positive["y"]["maneuver"] == spec5.MANEUVER_KINDS.index("dodge")
    samples.append(positive)
    return samples


def test_bc_v5_step_batch_is_finite_and_trains_maneuver_head():
    cfg = net.Config(schema=spec5.SCHEMA, hidden=16, head=4, seed=5)
    policy = backend.build(cfg, kind="torch", device="cpu")
    batch = _v5_bc_batch()
    assert any(s["y"]["maneuver"] != spec5.MANEUVER_NONE for s in batch)
    report = policy.step_batch(batch)
    for key in ("loss", "value", "plan", "target", "weapon", "maneuver"):
        assert key in report, f"в BC-отчёте v5 нет ключа {key}"
        assert math.isfinite(report[key]), f"{key} не конечен: {report[key]}"
    assert report["n"] == len(batch)


# --------------------------------------------------------------------------- 3. PPO v5 (act/eval/update)
def _agent_v5(seed=7):
    cfg = net.Config(schema=spec5.SCHEMA, hidden=16, head=4, seed=seed)
    return PPOAgent(backend.build(cfg, kind="torch", device="cpu"), ppo_epochs=2, minibatch=4)


def test_ppo_v5_act_samples_legal_maneuver_action():
    agent = _agent_v5()
    torch.manual_seed(0)
    env = polyenv.PolyFightEnv(rounds_cap=6, schema=spec5.SCHEMA)
    _name, payload = _stage43_payloads()[0]
    s = env.reset(payload)
    for _ in range(12):
        a = agent.act(s)["action"]
        assert "maneuver" in a
        assert joint.is_jointly_legal_v5(a, s["legal"])


def test_ppo_v5_rollout_logp_matches_update():
    agent = _agent_v5()
    torch.manual_seed(1)
    env = polyenv.PolyFightEnv(rounds_cap=6, schema=spec5.SCHEMA)
    _name, payload = _stage43_payloads()[0]
    s = env.reset(payload)
    out = agent.act(s)
    new_logp, _ent, _value, _logpi, _legal = agent._eval([s], [out["action"]])
    assert new_logp.shape == (1,)
    assert float(new_logp[0].item()) == pytest.approx(out["logp"], abs=1e-4)


def test_ppo_v5_update_runs_to_finite_report():
    agent = _agent_v5()
    torch.manual_seed(2)
    env = polyenv.PolyFightEnv(rounds_cap=6, schema=spec5.SCHEMA)
    _name, payload = _stage43_payloads()[0]
    s = env.reset(payload)
    out = agent.act(s)
    traj = {"sample": s, "action": out["action"], "logp": out["logp"], "adv": 0.5, "ret": 0.3}
    report = agent.update([traj, dict(traj)])
    assert report["n"] == 2
    for key in ("loss", "policy_loss", "value_loss", "entropy", "kl"):
        assert math.isfinite(report[key]), f"{key} не конечен: {report[key]}"


# --------------------------------------------------------------------------- 4. гейт-pуть v5 (ModelController → joint.decode)
def test_model_controller_v5_label_carries_maneuver_via_joint_decode():
    """Оценка/гейт идёт через ModelController.label -> joint.decode: для v5 ОБЯЗАН вернуться
    maneuver-ключ и 4D-легальность (иначе decode брал бы 3-головый head_logp по 4D-маске)."""
    env = polyenv.PolyFightEnv(rounds_cap=6, schema=spec5.SCHEMA)
    _name, payload = _stage43_payloads()[0]
    s = env.reset(payload)
    model = backend.build(net.Config(schema=spec5.SCHEMA, hidden=16, head=4, seed=9), kind="pure")
    ctrl = ModelController(model, schema=spec5.SCHEMA)
    label = ctrl.label(s, env._ctx, env.slots)
    assert "maneuver" in label                             # 4-е измерение присутствиевует
    assert joint.is_jointly_legal_v5(label, s["legal"])     # joint-decode вернул действие из A(s)
    # канон: maneuver!=NONE ⇒ target/weapon=NONE
    if label["maneuver"] != spec5.MANEUVER_NONE:
        assert label["target"] == spec.NONE_SLOT and label["weapon"] == spec.NONE_SLOT
    assert ctrl.last_baseline is not None                  # независимый baseline посчитан

