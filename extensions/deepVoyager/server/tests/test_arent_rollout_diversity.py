# tests/test_arent_rollout_diversity.py — WP5: разнообразие rollout (старт с разных актёров).
#
# Контракт: PolyFightEnv.reset принимает start_index — курсор встаёт на start_index-го
# живого бойца в порядке инициативы (по модулю состава), поэтому round-robin эпизоды
# одной и той же сцены стартуют с разных позиций и сеть играет за каждого юнита, а не
# только за вершину инициативы. Legacy-монactor FightEnv принимает тот же аргумент, но
# игнорирует (курсор жёстко привязан к герою). collect ведёт счётчик эпизодов на сцену
# и передаёт его в reset — вращение стартового актёра между боями одной сцены.
import random

import pytest

from arent import polyenv
from arent.env import FightEnv
from arent.polyenv import PolyFightEnv
from arent.rollout import RlConfig, collect
from arent.torch_rl import PPOAgent
from conftest import make_npc, make_scene_payload, make_weapon
from arent import backend, net

torch = pytest.importorskip("torch")

NOTHING = {"cell": 0, "target": -1, "weapon": -1}


def _scene():
    """2 на 2 с явной инициативой: порядок A1(20) -> F1(15) -> F2(10) -> A2(5)."""
    a1 = make_npc("A1", 0, 0, disposition=-1, hp=30, speed=30, initiative=20)
    a2 = make_npc("A2", 100, 0, disposition=-1, hp=30, speed=30, initiative=5)
    f1 = make_npc("F1", 50, 0, disposition=1, hp=30, speed=30, initiative=15)
    f1["weapons"] = [make_weapon("fsword", "меч", damage="1d6", sure_ft=5)]
    f2 = make_npc("F2", 350, 0, disposition=1, hp=30, speed=30, initiative=10)
    f2["weapons"] = [make_weapon("fbow", "лук", damage="1d8", sure_ft=30, doubt_ft=120)]
    payload = make_scene_payload(npcs=[a1, a2, f1, f2],
                                 weapons=[make_weapon("sword", damage="1d6+2")])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


def _duel(prefix):
    """Короткая 1x1 для collect: npcs[0].id различает сцены в spy-записях."""
    hero = make_npc(prefix + "1", 0, 0, disposition=-1, hp=50, speed=30, damage="1d8")
    foe = make_npc(prefix + "2", 50, 0, disposition=1, hp=50, speed=0, damage="1d8")
    payload = make_scene_payload(npcs=[hero, foe],
                                 weapons=[make_weapon(prefix + "sword", damage="1d6+2")],
                                 token=prefix + "2")
    payload.update({"src": prefix + "1", "speed": 30})   # src по умолчанию "A" — его нет в сцене
    return payload


def _agent():
    return PPOAgent(backend.build(net.Config(hidden=16, head=4, seed=3),
                                  kind="torch", device="cpu"),
                    ppo_epochs=2, minibatch=4)


#--- 1. reset(start_index): курсор на k-том живом по инициативе ------------------
def test_reset_start_index_zero_is_top_of_initiative():
    e = PolyFightEnv(rounds_cap=8)
    e.reset(_scene(), start_index=0)
    assert e.actor == "A1"


@pytest.mark.parametrize("k,uid", [(1, "F1"), (2, "F2"), (3, "A2")])
def test_reset_start_index_places_cursor_on_kth_actor(k, uid):
    e = PolyFightEnv(rounds_cap=8)
    e.reset(_scene(), start_index=k)
    assert e.actor == uid


def test_reset_start_index_wraps_modulo_roster():
    e = PolyFightEnv(rounds_cap=8)
    e.reset(_scene(), start_index=4)                   # 4 % 4 -> снова вершина
    assert e.actor == "A1"
    e.reset(_scene(), start_index=7)                   # 7 % 4 == 3 -> четвёртый в порядке
    assert e.actor == "A2"


def test_start_index_shifts_the_whole_traversal_not_just_first_step():
    e = PolyFightEnv(rounds_cap=8)
    e.reset(_scene(), start_index=1)
    seen = [e.actor]
    for _ in range(3):
        e.step(NOTHING)
        seen.append(e.actor)
    assert seen == ["F1", "F2", "A2", "A1"]            # обход — полный цикл, старт сдвинулся


#--- 2. legacy-монactor: аргумент принимается и игнорируется ---------------------
def test_monactor_reset_accepts_start_index_but_stays_hero_fixed():
    plain = FightEnv(rounds_cap=8).reset(_scene())
    shifted = FightEnv(rounds_cap=8).reset(_scene(), start_index=2)
    assert shifted == plain                             # герой-курсор не смешается


#--- 3. collect: раунды одной сцены стартуют с разных актёров --------------------
def test_collect_rotates_start_indices_across_episodes(monkeypatch):
    recorded = []
    orig = polyenv.PolyFightEnv.reset

    def spy(self, payload, start_index=0):
        recorded.append((payload["data"]["npcs"][0]["id"], start_index))
        return orig(self, payload, start_index=start_index)

    monkeypatch.setattr(polyenv.PolyFightEnv, "reset", spy)
    torch.manual_seed(0)
    collect(_agent(), [("a", _duel("A")), ("b", _duel("B"))],
            RlConfig(rollout_steps=12, rounds_cap=1, seed=4), random.Random(4))
    for prefix in ("A", "B"):
        seen = [i for uid, i in recorded if uid == prefix + "1"]
        assert len(seen) >= 2                           # сцена пережила несколько эпизодов
        assert seen == list(range(len(seen)))           # 0,1,2,... — ротация без пропусков


def test_collect_legacy_monactor_tolerates_rotation():
    torch.manual_seed(0)
    buf = collect(_agent(), [("a", _duel("A"))],
                  RlConfig(rollout_steps=4, rounds_cap=1, seed=4, polyactor=False),
                  random.Random(4))
    assert len(buf) == 4                                 # start_index проигнорирован, не упал
