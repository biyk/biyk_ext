# tests/test_arent_rl_v3.py — F-B.3b-2: PPO-контур схемы 3 (move-plan) — collect + мини-прогон.
#
# torch обязателен (importorskip). Проверяем, что после threading-а ключа действия через
# policy.ykey rollout собирает буфер с план-действиями (plan, а не cell), а rl.run одним
# итерационным smoke пишет чекпойнт схемы 3 (dims=spec3, schema=3). Большое обучение НЕ
# запускаем: один итерация, крошечный rollout, warm=None (случайные веса).
import pytest

from arent import backend, dataset, net, paths, rl, spec3
from arent.rollout import RlConfig, collect
from arent.torch_rl import PPOAgent

torch = pytest.importorskip("torch")


def _scenes(n=5, seed=11):
    pool, _manifest = dataset.scenario_sources(n, seed)
    assert pool, "генератор обязан выдать боеспособные командные сцены"
    return [(name, payload) for name, payload in pool]


def _v3_agent():
    cfg = net.Config(schema=3, hidden=16, head=4, seed=3)
    return PPOAgent(backend.build(cfg, kind="torch", device="cpu"), ppo_epochs=2, minibatch=4)


def test_collect_schema3_buffer_uses_plan_actions():
    import random
    agent = _v3_agent()
    rcfg = RlConfig(rollout_steps=6, rounds_cap=3, seed=4, schema=3)
    buf = collect(agent, _scenes(2), rcfg, random.Random(4))
    assert len(buf) == 6
    for row in buf:
        assert "plan" in row["action"] and "cell" not in row["action"]
        assert set(row["action"]) == {"plan", "target", "weapon"}


def test_rl_run_schema3_smoke_saves_plan_checkpoint(tmp_path):
    prev = paths.workspace()
    paths.set_workspace(str(tmp_path))
    try:
        net_cfg = net.Config(schema=3, hidden=16, head=4, seed=3)
        rcfg = RlConfig(iters=1, rollout_steps=8, rounds_cap=3, eval_every=1, replays=1, seed=5)
        result = rl.run(name="ppo_v3", warm=None, rcfg=rcfg, net_cfg=net_cfg, kind="torch",
                        device="cpu", scenario_sources=_scenes(5), log=lambda *a: None)
        assert result["summary"]["dims"] == spec3.dims3()
        assert result["summary"]["rl"]["schema"] == 3
        ckpt = net.load(result["best_checkpoint"], expect_schema=3)
        assert ckpt["schema"] == 3 and ckpt["config"]["schema"] == 3
        assert ckpt["dims"] == spec3.dims3()
    finally:
        paths.set_workspace(prev)
