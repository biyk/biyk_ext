# tests/test_arent_env.py — RL-среда поверх Simulation: шаг, терминал, награда в одном месте.
#
# Проверяем инварианты, а не красивые числа: reset даёт наблюдение фиксированной схемы,
# step декодирует тройку индексов в advance и честно считает done (смерть / зачистка /
# потолок раундов); shape_reward — чистая функция (нормировка + только терминальные бонусы);
# среда детерминирована при одном входе и не зависит от разметки/meta.
import pytest

from arent import env, spec
from arent.env import FightEnv, shape_reward
from conftest import make_npc, make_scene_payload, make_weapon


def _fight_scene(foe_hp=1, hero_hp=50):
    hero = make_npc("A", 0, 0, disposition=-1, hp=hero_hp, speed=30, damage="1d8")
    foe = make_npc("B", 50, 0, disposition=1, hp=foe_hp, speed=0, damage="1d8")
    return make_scene_payload(npcs=[hero, foe],
                              weapons=[make_weapon("sword", damage="1d6+2")], token="B")


ATTACK = {"cell": 0, "target": 0, "weapon": 0}
NOTHING = {"cell": 0, "target": -1, "weapon": -1}


def test_reset_returns_observation_with_schema_and_masks():
    e = FightEnv(rounds_cap=8)
    sample = e.reset(_fight_scene())
    assert sample["schema"] == spec.SCHEMA
    d = spec.dims()
    assert len(sample["state"]) == d["state"]
    assert len(sample["mask"]["cells"]) == d["cells"]
    assert len(sample["mask"]["targets"]) == d["targets"]
    assert len(sample["mask"]["weapons"]) == d["weapons"]


def test_step_clears_lone_foe_and_flags_done():
    e = FightEnv(rounds_cap=8)
    e.reset(_fight_scene(foe_hp=1))
    nxt, reward, done, info = e.step(ATTACK)
    assert done is True and info["cleared"] is True and info["survived"] is True
    assert nxt is None and reward > 0            # зачистка + выживание дают терминальные бонусы


def test_step_without_attack_leaves_foe_alive():
    e = FightEnv(rounds_cap=8)
    e.reset(_fight_scene(foe_hp=50))
    nxt, reward, done, info = e.step(NOTHING)
    assert done is False and info["cleared"] is False and info["survived"] is True
    assert isinstance(nxt, dict)                 # не терминал -> следующее наблюдение


def test_rounds_cap_forces_done():
    e = FightEnv(rounds_cap=1)
    e.reset(_fight_scene(foe_hp=999, hero_hp=999))
    _nxt, _r, done, info = e.step(NOTHING)
    assert done is True and info["rounds"] == 1  # уткнулись в потолок раундов


def test_death_is_terminal_with_no_survive_bonus():
    e = FightEnv(rounds_cap=8, survive_bonus=1.0, clear_bonus=1.0)
    e.reset(_fight_scene(foe_hp=999, hero_hp=1))
    _nxt, reward, done, info = e.step(NOTHING)   # хрупкий герой гибнет от ответного удара
    assert done is True and info["survived"] is False and info["cleared"] is False


def test_shape_reward_normalizes_and_only_adds_terminal_bonuses():
    # промежуточный шаг: без терминала бонусов нет, масштаб ~ value / VALUE_SCALE
    mid = shape_reward(30.0, done=False, survived=True, cleared=True,
                       survive_bonus=1.0, clear_bonus=1.0)
    assert mid == pytest.approx(30.0 / spec.VALUE_SCALE, abs=1e-6)
    term = shape_reward(30.0, done=True, survived=True, cleared=True,
                        survive_bonus=1.0, clear_bonus=1.0)
    assert term == pytest.approx(mid + 2.0, abs=1e-6)
    dead = shape_reward(0.0, done=True, survived=False, cleared=False,
                        survive_bonus=1.0, clear_bonus=1.0)
    assert dead == 0.0


def test_env_is_deterministic_for_the_same_actions():
    def rollout():
        e = FightEnv(rounds_cap=8)
        e.reset(_fight_scene(foe_hp=50))
        out, done = [], False
        actions = [ATTACK, NOTHING, NOTHING]
        for i in range(3):
            _n, r, done, info = e.step(actions[i])
            out.append((round(r, 6), done, info["cleared"], info["survived"]))
            if done:
                break
        return out
    assert rollout() == rollout()
