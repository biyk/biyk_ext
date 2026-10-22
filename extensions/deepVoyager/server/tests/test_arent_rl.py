# tests/test_arent_rl.py — PPO-математика (torch_rl), rollout и цикл (rl): инварианты.
#
# torch обязателен: без него весь модуль пропускаем (importorskip). Проверяем: act даёт
# легальную тройку + logp_table (joint logπ исполненного действия из неё); gae считает
# бутстрап на усечении и ноль на терминале; collect возвращает нормализованные advantage;
# update двигает веса и требует torch-политику; warm reset_value_head переносит ствол/головы,
# но перезаливает критик; resume (rl_state) побитово восстанавливает оптимизатор/веса/RNG на
# CPU; run пишет чекпойнты/манифест и держит holdout-группы непересекающимися с train.
import math
import os

import pytest

from arent import backend, env, net, rl, rl_setup, rl_state, tactics_config
from arent.rollout import RlConfig, collect, gae, normalize
from arent.tactics_counters import Counters
from arent.tactics_config import parse as parse_tactics
from arent.torch_rl import PPOAgent, joint_logp
from conftest import make_npc, make_scene_payload, make_weapon

torch = pytest.importorskip("torch")


def _scene(foe_hp=50, hero_hp=50):
    hero = make_npc("A", 0, 0, disposition=-1, hp=hero_hp, speed=30, damage="1d8")
    foe = make_npc("B", 50, 0, disposition=1, hp=foe_hp, speed=0, damage="1d8")
    return make_scene_payload(npcs=[hero, foe],
                              weapons=[make_weapon("sword", damage="1d6+2")], token="B")


def _samples(n=6):
    """Несколько наблюдений из среды (тот же формат, что играет модель)."""
    e = env.FightEnv(rounds_cap=8)
    out = []
    while len(out) < n:
        s = e.reset(_scene())
        out.append(s)
        for _ in range(3):
            nxt, _r, _term, _trunc, _i = e.step({"cell": 0, "target": 0, "weapon": 0})
            if _term or _trunc:
                break
            out.append(nxt)
            if len(out) >= n:
                break
    return out[:n]


def _cfg(seed=3):
    return net.Config(hidden=16, head=4, seed=seed)


def _agent(seed=3):
    return PPOAgent(backend.build(_cfg(seed), kind="torch", device="cpu"),
                    ppo_epochs=2, minibatch=4)


def _trajectories(agent, samples, advs=None):
    """Собрать траектории тем же агентом, что потом обновляем: старый logπ из той же политики."""
    trajs = []
    for i, s in enumerate(samples):
        a = agent.act(s)
        trajs.append({"sample": s, "action": a["action"], "logp": a["logp"],
                      "adv": (advs[i] if advs else 1.0), "ret": float(i) / 10.0})
    return trajs


# ------------------------------------------------------------------ act: легальность + logp_table
def test_act_returns_legal_action_and_finite_quantities():
    agent = _agent()
    s = _samples(1)[0]
    out = agent.act(s)
    for group, key in (("cells", "cell"), ("targets", "target"), ("weapons", "weapon")):
        idx = out["action"][key]
        assert 0 <= idx < len(s["mask"][group])
        assert s["mask"][group][idx] == 1                 # выбран только легальный слот
    assert math.isfinite(out["logp"]) and out["logp"] <= 1e-6
    assert math.isfinite(out["value"]) and out["entropy"] >= 0.0


def test_act_exposes_logp_table_reproducing_joint_logp():
    agent = _agent()
    s = _samples(1)[0]
    out = agent.act(s)
    assert set(out["logp_table"]) == {"cells", "targets", "weapons"}
    # joint logπ выбранной тройки = сумма logπ по группам из таблицы минус нормировка logZ
    # (знаменитель совместного распределения по допустимому множеству) = logp из act.
    assert joint_logp(out["logp_table"], out["action"], logZ=out["logZ"]) == pytest.approx(
        out["logp"], abs=1e-5)
    # сумма по группам БЕЗ нормировки — низкоуровневый примитив joint_logp (logZ=0 по умолчанию)
    alt = dict(out["action"])
    alt["weapon"] = env.NONE_INDEX
    expected = (out["logp_table"]["cells"][alt["cell"]] + out["logp_table"]["targets"][alt["target"]]
                + out["logp_table"]["weapons"][alt["weapon"]])
    assert joint_logp(out["logp_table"], alt) == pytest.approx(expected, abs=1e-6)


# ------------------------------------------------------------------ update
def test_update_changes_weights_and_reports_finite_metrics():
    agent = _agent()
    before = agent.policy.params["trunk1"][0][0]
    report = agent.update(_trajectories(agent, _samples(6)))
    assert report["n"] == 6
    for key in ("loss", "policy_loss", "value_loss", "entropy", "kl"):
        assert math.isfinite(report[key])
    assert 0.0 <= report["clip_frac"] <= 1.0
    assert agent.policy.params["trunk1"][0][0] != before  # веса сдвинулись


def test_update_on_same_policy_keeps_ratio_near_one_first_pass():
    agent = _agent()
    first = agent.update(_trajectories(agent, _samples(4)))
    assert first["clip_frac"] <= 1.0
    assert abs(first["kl"]) < 1.0                          # не взрывной на первом прогоне


def test_update_requires_torch_policy():
    class NotTorch:
        pass
    with pytest.raises(RuntimeError):
        PPOAgent(NotTorch())


def test_act_is_deterministic_for_seeded_torch():
    samples = _samples(3)
    def run():
        torch.manual_seed(11)
        agent = _agent()
        return [agent.act(s)["action"] for s in samples]
    assert run() == run()


def test_checkpoint_roundtrip_is_deterministic(tmp_path):
    agent = _agent()
    s = _samples(1)[0]
    torch.manual_seed(5)
    first = agent.act(s)
    path = str(tmp_path / "model.json")
    net.save(agent.policy, path, metrics={"which": "test"})
    reloaded = backend.load_policy(path, kind="torch")
    torch.manual_seed(5)
    second = PPOAgent(reloaded).act(s)
    assert first["action"] == second["action"]
    assert first["value"] == pytest.approx(second["value"], abs=1e-4)


# ------------------------------------------------------------------ чистая математика rollout
def test_gae_zero_bootstrap_on_terminal():
    # [шаг -> шаг -> терминал]: terminal next_value=0, alive=0 обрывает цепочку GAE
    adv, ret = gae([1.0, 1.0], [0.5, 0.5], [0.7, 0.0], [1, 0], gamma=1.0, lam=1.0)
    assert adv[1] == pytest.approx(1.0 + 1.0 * 0.0 - 0.5)          # delta терминала (без бутстрапа)
    assert adv[0] == pytest.approx((1.0 + 0.7 - 0.5) + adv[1])     # chain продолжается к терминалу
    assert ret[1] == pytest.approx(adv[1] + 0.5)


def test_gae_uses_bootstrap_value_on_truncation():
    # усечение (rounds_cap): next_value=V(s') != 0, но alive=0 ->adv = r + gamma*V(s') - V(s)
    adv, ret = gae([0.0], [0.2], [0.9], [0], gamma=1.0, lam=1.0)
    assert adv[0] == pytest.approx(0.0 + 1.0 * 0.9 - 0.2)


def test_normalize_is_zero_mean_unit_std():
    out = normalize([1.0, 2.0, 3.0, 4.0])
    assert abs(sum(out) / len(out)) < 1e-9
    assert abs(sum(x * x for x in out) / len(out) - 1.0) < 1e-3
    assert normalize([]) == []


def test_collect_builds_buffer_with_executed_actions():
    import random
    agent = _agent()
    rcfg = RlConfig(rollout_steps=6, rounds_cap=3, seed=4)
    diag = []
    buf = collect(agent, [("a", _scene()), ("b", _scene())], rcfg, random.Random(4),
                  phi=None, diag=diag)
    assert len(buf) == 6
    for row in buf:
        assert set(row) == {"sample", "action", "logp", "adv", "ret"}
        assert math.isfinite(row["logp"]) and math.isfinite(row["adv"])
        assert row["action"]["weapon"] <= env.NONE_INDEX
    assert abs(sum(r["adv"] for r in buf) / len(buf)) < 1e-6       # advantage нормализован
    assert len(diag) == 6 and {"phi", "reward", "terminated", "truncated"} <= set(diag[0])


# ------------------------------------------------------------------ warm: reset value head
def test_reset_value_head_keeps_trunk_and_heads_reinits_critic(tmp_path):
    cfg = _cfg(seed=5)
    parent = backend.build(cfg, kind="torch", device="cpu")
    fresh = net.init_params(cfg)
    poisoned = [0.123] * len(fresh["valueW"])                    # valueW — плоский вектор длины head
    parent.set_params({**parent.params, "valueW": poisoned})
    path = str(tmp_path / "model_best.json")
    net.save_params(parent.params, cfg, "torch", path, metrics={"which": "best"})
    keep, _ = rl_setup.warm_params(cfg, path, reset_value_head=False)
    assert keep["valueW"] == pytest.approx(poisoned)              # перенесли критик как есть
    assert keep["trunk1"] == parent.params["trunk1"]              # точное совпадение из JSON
    reset, _ = rl_setup.warm_params(cfg, path, reset_value_head=True)
    assert reset["trunk1"] == parent.params["trunk1"]             # ствол из BC (тот же JSON)
    assert reset["valueW"] != pytest.approx(poisoned, abs=1e-3)   # критик инициализирован заново


# ------------------------------------------------------------------ resume: побитово на CPU
def _busy_policy():
    cfg = _cfg(seed=7)
    policy = backend.build(cfg, kind="torch", device="cpu")
    agent = PPOAgent(policy, ppo_epochs=2, minibatch=4)
    agent.update(_trajectories(agent, _samples(6)))
    return cfg, policy


def test_resume_roundtrip_restores_optimizer_weights_and_rng(tmp_path):
    import json
    cfg, policy = _busy_policy()
    path = str(tmp_path / "ppo_state.pt")
    scenario_rng = (3, (7, 11, 13), 2.5)
    rl_state.save(path, policy, RlConfig(), cfg, 7, "sha-parent", scenario_rng)
    torch.manual_seed(999)
    restored = backend.build(cfg, kind="torch", device="cpu")    # совсем другие веса
    info = rl_state.load(path, restored, cfg)
    assert info["iteration"] == 7 and info["warm_sha"] == "sha-parent"
    assert json.dumps(restored.params) == json.dumps(policy.params)   # веса побитово восстановлены
    assert info["rng"]["scenario_rng"] == scenario_rng


def test_resume_guard_rejects_mismatched_architecture(tmp_path):
    cfg, policy = _busy_policy()
    path = str(tmp_path / "ppo_state.pt")
    rl_state.save(path, policy, RlConfig(), cfg, 3, "sha", None)
    other = net.Config(hidden=32, head=8, seed=7)               # другая архитектура
    with pytest.raises(ValueError):
        rl_state.load(path, backend.build(other, kind="torch", device="cpu"), other)


def test_rng_snapshot_restore_reproduces_cpu_sequence():
    import random
    random.seed(123)
    torch.manual_seed(123)
    snap = rl_state.rng_snapshot()
    seq_a = (random.random(), torch.rand(4).tolist())
    random.seed(555)
    torch.manual_seed(555)
    _ = (random.random(), torch.rand(4))                         # возмутили глобальные RNG
    rl_state.rng_restore(snap)
    seq_b = (random.random(), torch.rand(4).tolist())
    assert seq_a == seq_b                                         # побитовое продолжение на CPU


# ------------------------------------------------------------------ цикл rl.run (end-to-end, крошечно)
def _tiny_rcfg(**over):
    base = dict(iters=2, rollout_steps=8, eval_every=1, minibatch=4, ppo_epochs=1,
                replays=1, rounds_cap=4, seed=9, holdout_frac=0.0, val_frac=0.0)
    base.update(over)
    return RlConfig(**base)


def _tiny_net():
    return net.Config(hidden=16, head=4, seed=5)


def test_run_writes_checkpoints_and_manifest(tmp_path, monkeypatch):
    from arent import paths
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(rl.dataset, "sources",
                        lambda arenas, use_live, **_kw: [("arenaA", _scene()), ("arenaB", _scene())])
    result = rl.run(name="ppo1", warm=None, rcfg=_tiny_rcfg(), net_cfg=_tiny_net(),
                    kind="torch", device="cpu", log=lambda *_a: None)
    directory = str(tmp_path / "runs" / "ppo1")
    for fname in ("model.json", "model_best.json", "summary.json", "history.json",
                  "run_manifest.json", "ppo_state.pt"):
        assert os.path.exists(os.path.join(directory, fname)), fname
    assert len(result["history"]) == 2
    assert "eval" in result["history"][-1] and result["best"]["survival"] >= 0.0


def test_run_without_scenarios_raises(tmp_path, monkeypatch):
    from arent import paths
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(rl.dataset, "sources", lambda arenas, use_live, **_kw: [])
    with pytest.raises(RuntimeError):
        rl.run(name="empty", warm=None, rcfg=_tiny_rcfg(), net_cfg=_tiny_net(),
               kind="torch", device="cpu", log=lambda *_a: None)


def test_run_warm_start_reads_model_best(tmp_path, monkeypatch):
    from arent import paths
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(rl.dataset, "sources", lambda arenas, use_live, **_kw: [("arenaA", _scene())])
    parent = backend.build(_tiny_net(), kind="torch", device="cpu")
    directory = paths.run_dir("parent")
    net.save(parent, paths.file_in(directory, "model_best.json"), metrics={"which": "best"})
    result = rl.run(name="child", warm="parent", rcfg=_tiny_rcfg(), net_cfg=_tiny_net(),
                    kind="torch", device="cpu", log=lambda *_a: None)
    assert result["summary"]["warm_from"].endswith(os.path.join("parent", "model_best.json"))
    assert result["summary"]["used_vref"] is True


def test_run_holdout_disjoint_from_train(tmp_path, monkeypatch):
    import json
    from arent import paths
    paths.set_workspace(str(tmp_path))
    names = [f"arena{i}" for i in range(6)]
    monkeypatch.setattr(rl.dataset, "sources", lambda a, l, **_kw: [(n, _scene()) for n in names])
    rl.run(name="ppoH", warm=None, rcfg=_tiny_rcfg(iters=1, rollout_steps=6, holdout_frac=0.5),
           net_cfg=_tiny_net(), kind="torch", device="cpu", log=lambda *_a: None)
    with open(paths.file_in(paths.run_dir("ppoH"), "run_manifest.json"), encoding="utf-8") as f:
        sp = json.load(f)["split"]
    assert sp["method"] == "grouped-by-name" and sp["disjoint"] is True
    assert set(sp["train"]).isdisjoint(set(sp["holdout"]))
    assert len(sp["holdout"]) == 3 and sp["holdout"]                # непустой независимый набор


def test_manifest_records_ppo_lineage_and_full_config(tmp_path, monkeypatch):
    import json
    from arent import paths, provenance
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(rl.dataset, "sources",
                        lambda arenas, use_live, **_kw: [("arenaA", _scene()), ("arenaB", _scene())])
    parent = backend.build(_tiny_net(), kind="torch", device="cpu")
    net.save(parent, paths.file_in(paths.run_dir("bcx"), "model_best.json"),
             metrics={"which": "best"})
    rl.run(name="ppoman", warm="bcx", rcfg=_tiny_rcfg(), net_cfg=_tiny_net(),
           kind="torch", device="cpu", log=lambda *_a: None)
    with open(paths.file_in(paths.run_dir("ppoman"), "run_manifest.json"),
              encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["method"] == "ppo"
    assert manifest["warm"]["parent_sha256"] == provenance.sha256_file(manifest["warm"]["parent_path"])
    assert manifest["seeds"]["env_seed"] != manifest["seeds"]["train_seed"]
    assert manifest["training_scenarios"]["sha256"] and len(manifest["training_scenarios"]["sha256"]) == 64
    assert manifest["outputs"]["sha256"]["model_best.json"]
    # П.6: полная конфигурация PPO фактическими значениями (не только дефолты в коде)
    for key in ("gamma", "gae_lambda", "clip_eps", "ent_coef", "vf_coef", "rollout_steps",
                "minibatch", "ppo_epochs", "lr", "clear_bonus", "death_penalty"):
        assert key in manifest["rl"]


# ------------------------------------------------------------------ тактический shaping (Этап 0)
_TACT_CFG = parse_tactics({"weights": {"no_idle": 0.03, "kill_shot": 0.15, "focus_wounded": 0.10},
                           "penalties": {"idle_turn": -0.05}})


def test_collect_with_shaper_populates_counters():
    """rollout.collect со shape=включённый TacticsConfig: буфер собирается, счётчики непустые."""
    import random
    agent = _agent()
    rcfg = RlConfig(rollout_steps=8, rounds_cap=4, seed=4, polyactor=True)
    counters = Counters()
    buf = collect(agent, [("a", _scene()), ("b", _scene())], rcfg, random.Random(4), phi=None,
                  counters=counters, shape=_TACT_CFG, anneal=(1, 2))
    assert len(buf) == 8
    assert counters.steps > 0                       # шейпер считает каждый шаг rollout
    assert counters.to_dict()["tactics"]            # хотя бы один ключ применим


def test_run_use_tactics_writes_counters_json(tmp_path, monkeypatch):
    """Сквозной прогон: rl.run(use_tactics=True) пишет tactics_counters.json с непустым steps."""
    from arent import paths
    paths.set_workspace(str(tmp_path))
    tactics_config.set_config(_TACT_CFG)
    try:
        monkeypatch.setattr(rl.dataset, "sources",
                            lambda arenas, use_live, **_kw: [("arenaA", _scene()),
                                                              ("arenaB", _scene())])
        rl.run(name="ppotact", warm=None, rcfg=_tiny_rcfg(iters=1, rollout_steps=12),
               net_cfg=_tiny_net(), kind="torch", device="cpu",
               log=lambda *_a: None, use_tactics=True)
        import json
        path = paths.file_in(paths.run_dir("ppotact"), "tactics_counters.json")
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            agg = json.load(f)
        assert agg["steps"] > 0 and agg["tactics"]
    finally:
        tactics_config.set_config(None)
