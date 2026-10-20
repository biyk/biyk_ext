# tests/test_arent_rl.py — PPO-математика (torch_rl) и цикл (rl): инварианты, не числа.
#
# torch обязателен: без него весь модуль пропускаем (importorskip). Проверяем, что act
# возвращает легальную тройку в границах масок с конечными logp/value/entropy; update
# двигает веса и считает ratio/clip/entropy; update требует torch-политику (ошибка на pure);
# чекпойнт переживает round-trip (save -> load_policy -> детерминированный act).
import math
import os

import pytest

from arent import backend, env, net, rl
from arent.rollout import RlConfig, gae, normalize
from arent.torch_rl import PPOAgent
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
            nxt, _r, done, _i = e.step({"cell": 0, "target": 0, "weapon": 0})
            if done:
                break
            out.append(nxt)
            if len(out) >= n:
                break
    return out[:n]


def _agent(seed=3):
    cfg = net.Config(hidden=16, head=4, seed=seed)
    policy = backend.build(cfg, kind="torch", device="cpu")
    return PPOAgent(policy, ppo_epochs=2, minibatch=4)


def _trajectories(agent, samples, advs=None):
    """Собрать траектории тем же агентом, что потом обновляем: старый logπ из той же политики."""
    trajs = []
    for i, s in enumerate(samples):
        a = agent.act(s)
        trajs.append({"sample": s, "action": a["action"], "logp": a["logp"],
                      "adv": (advs[i] if advs else 1.0), "ret": float(i) / 10.0})
    return trajs


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
def test_gae_chain_and_bootstrap():
    # один не-терминальный шаг за двумя: возврат терминали не бутстрапится, done обрывает цепочку
    adv, ret = gae([1.0, 1.0], [0.5, 0.5], [False, True], gamma=1.0, lam=1.0, bootstrap=0.0)
    assert ret[1] == pytest.approx(adv[1] + 0.5)
    assert adv[1] == pytest.approx(0.5)                       # delta = 1 + 0 - 0.5
    assert adv[0] == pytest.approx(1.5)                       # + lam*next (chain не обрван)


def test_normalize_is_zero_mean_unit_std():
    out = normalize([1.0, 2.0, 3.0, 4.0])
    assert abs(sum(out) / len(out)) < 1e-9
    assert abs(sum(x * x for x in out) / len(out) - 1.0) < 1e-3
    assert normalize([]) == []


# ------------------------------------------------------------------ цикл rl.run (end-to-end, крошечно)
def _tiny_rcfg(**over):
    base = dict(iters=2, rollout_steps=8, eval_every=1, minibatch=4, ppo_epochs=1,
                replays=1, rounds_cap=4, seed=9)
    base.update(over)
    return RlConfig(**base)


def _tiny_net():
    return net.Config(hidden=16, head=4, seed=5)


def test_run_writes_checkpoints_and_manifest(tmp_path, monkeypatch):
    from arent import paths
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(rl.dataset, "sources",
                        lambda arenas, use_live: [("arenaA", _scene()), ("arenaB", _scene())])
    result = rl.run(name="ppo1", warm=None, rcfg=_tiny_rcfg(), net_cfg=_tiny_net(),
                    kind="torch", device="cpu", log=lambda *_a: None)
    directory = str(tmp_path / "runs" / "ppo1")
    for name in ("model.json", "model_best.json", "summary.json", "history.json",
                 "run_manifest.json"):
        assert os.path.exists(os.path.join(directory, name)), name
    assert len(result["history"]) == 2
    assert "eval" in result["history"][-1] and result["best"]["survival"] >= 0.0


def test_run_without_scenarios_raises(tmp_path, monkeypatch):
    from arent import paths
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(rl.dataset, "sources", lambda arenas, use_live: [])
    with pytest.raises(RuntimeError):
        rl.run(name="empty", warm=None, rcfg=_tiny_rcfg(), net_cfg=_tiny_net(),
               kind="torch", device="cpu", log=lambda *_a: None)


def test_run_warm_start_reads_model_best(tmp_path, monkeypatch):
    from arent import paths
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(rl.dataset, "sources", lambda arenas, use_live: [("arenaA", _scene())])
    # подготовим runs/parent/model_best.json маленькими весами нужной формы
    parent = backend.build(_tiny_net(), kind="torch", device="cpu")
    directory = paths.run_dir("parent")
    net.save(parent, paths.file_in(directory, "model_best.json"), metrics={"which": "best"})
    result = rl.run(name="child", warm="parent", rcfg=_tiny_rcfg(), net_cfg=_tiny_net(),
                    kind="torch", device="cpu", log=lambda *_a: None)
    assert result["summary"]["warm_from"].endswith(os.path.join("parent", "model_best.json"))


def test_manifest_records_ppo_lineage(tmp_path, monkeypatch):
    import json
    from arent import paths, provenance
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(rl.dataset, "sources",
                        lambda arenas, use_live: [("arenaA", _scene()), ("arenaB", _scene())])
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
