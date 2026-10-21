# tests/test_arent_env_v3.py — F-B.3b-2: полиакторная PPO-среда схемы 3 (move-plan).
#
# Схема 3 в RL-контуре: среда наблюдает encode_v3 (plan-голова), легализует тройку
# (plan,target,weapon) и исполняет ход через Simulation.apply_actor_seq — удар из attack_cell,
# затем отступление. Legacy-мон.actor схемы 3 не поддерживается (advance сворачивает ход в
# финальную клетку) и обязан отвергаться. Тесты без torch (среда + rollout-фабрика).
import pytest

from arent import spec3
from arent.polyenv import PolyFightEnv
from arent.rollout import RlConfig, _make_env
from arent.team_reward import TeamReward
from conftest import make_npc, make_scene_payload, make_weapon


def _scene():
    a1 = make_npc("A1", 0, 0, disposition=-1, hp=30, speed=30, initiative=20)
    a2 = make_npc("A2", 200, 0, disposition=-1, hp=30, speed=30, initiative=5)
    f1 = make_npc("F1", 150, 0, disposition=1, hp=30, speed=30, initiative=15)
    f1["weapons"] = [make_weapon("fsword", "клик. меч", damage="1d6", sure_ft=5)]
    payload = make_scene_payload(npcs=[a1, a2, f1],
                                 weapons=[make_weapon("sword", damage="1d6+2", sure_ft=5, doubt_ft=30)])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


def _env3():
    e = PolyFightEnv(rounds_cap=20, team=TeamReward(draw_window=99), schema=3)
    obs = e.reset(_scene())
    return e, obs


def test_v3_env_observes_plan_head():
    e, obs = _env3()
    assert obs["schema"] == spec3.SCHEMA == 3
    assert len(obs["cells"][0]) == len(spec3.CELL3_FEATURES)
    assert len(obs["mask"]["cells"]) == spec3.K_MOVEPLAN + 1
    assert e.slots.plans and e.slots.n_plans == len(e.slots.plans)


def test_v3_action_space_can_express_attack_then_retreat():
    e, _obs = _env3()
    # хотя бы один план уходит с позиции удара (end != attack) — «выстрелил и отошёл» представим
    retreat = [p for p in e.slots.plans if p["attack_cell"] != p["end_cell"]]
    assert retreat, "среда v3 обязана перечислять планы с отступлением после удара"
    # и хотя бы один план бьёт не из исходной клетки (подход к цели)
    assert any(p["dirs_in"] for p in e.slots.plans)


def test_v3_step_legalizes_plan_and_advances_cursor():
    e, _obs = _env3()
    actor = e.actor
    nxt, reward, terminated, truncated, info = e.step({"plan": 0, "target": -1, "weapon": -1})
    assert info["action"]["plan"] == 0 and "cell" not in info["action"]
    assert info["actor"] == actor
    assert not terminated or nxt is None
    if nxt is not None:
        assert nxt["schema"] == 3


def test_rollout_builds_v3_polyenv_and_rejects_v3_monactor():
    cfg = RlConfig(schema=3)
    assert cfg.schema == 3
    made = _make_env(cfg, TeamReward())
    assert isinstance(made, PolyFightEnv) and made.schema == 3
    with pytest.raises(RuntimeError, match="полиактор"):
        _make_env(RlConfig(schema=3, polyactor=False), None)
