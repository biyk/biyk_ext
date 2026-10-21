# tests/test_arent_env.py — RL-среда поверх Simulation: шаг, terminal/truncated, потенциал.
#
# Проверяем инварианты, а не красивые числа: reset даёт наблюдение фиксированной схемы;
# step возвращает (next|None, reward, terminated, truncated, info) и честный ИСПОЛНЕННЫЙ
# action (легализованный). terminated = смерть/зачистка (конец игры), truncated = потолок
# раундов на продолжающемся бою (без терминальной награды). shape_reward = исход боя +
# потенциальный shaping gamma*Phi(s')-Phi(s) с Phi(терминал)=0: проверка телескопической
# инвариантности суммы shaping. Среда детерминирована при одном входе.
import pytest

from arent import spec
from arent.env import FightEnv, NONE_INDEX, shape_reward
from conftest import make_npc, make_scene_payload, make_weapon


def _fight_scene(foe_hp=1, hero_hp=50):
    """Герой A в клетке (0,0), один враг B в соседней клетке (x=50) — ближняя атака достает."""
    hero = make_npc("A", 0, 0, disposition=-1, hp=hero_hp, speed=30, damage="1d8")
    foe = make_npc("B", 50, 0, disposition=1, hp=foe_hp, speed=0, damage="1d8")
    return make_scene_payload(npcs=[hero, foe],
                              weapons=[make_weapon("sword", damage="1d6+2")], token="B")


def _far_scene(hero_hp=50):
    """Враг в 9 клетках: с текущей клетки ближняя атака НЕ достает -> legalize уберёт оружие."""
    hero = make_npc("A", 0, 0, disposition=-1, hp=hero_hp, speed=30, damage="1d8")
    foe = make_npc("B", 450, 0, disposition=1, hp=999, speed=0, damage="1d8")
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


def test_clear_is_terminated_with_clear_bonus():
    e = FightEnv(rounds_cap=8, clear_bonus=1.0, death_penalty=-1.0)
    e.reset(_fight_scene(foe_hp=1))
    nxt, reward, terminated, truncated, info = e.step(ATTACK)
    assert terminated is True and truncated is False
    assert info["cleared"] is True and info["survived"] is True
    assert nxt is None                                  # истинный терминал -> нет next-наблюдения
    assert reward == pytest.approx(1.0, abs=1e-6)       # без shaping: чистый clear_bonus


def test_no_attack_intermediate_is_not_terminal():
    e = FightEnv(rounds_cap=8)
    e.reset(_fight_scene(foe_hp=50))
    nxt, reward, terminated, truncated, info = e.step(NOTHING)
    assert terminated is False and truncated is False
    assert info["cleared"] is False and info["survived"] is True
    assert isinstance(nxt, dict)                        # продолжение -> следующее наблюдение
    assert reward == pytest.approx(0.0, abs=1e-6)       # нет исхода и нет Phi -> shaping 0


def test_rounds_cap_is_truncated_not_terminated_no_terminal_reward():
    # technical truncation of an ongoing fight: NOT terminated, NO terminal-outcome reward
    e = FightEnv(rounds_cap=1, clear_bonus=5.0, death_penalty=-5.0)
    e.reset(_fight_scene(foe_hp=999, hero_hp=999))
    nxt, reward, terminated, truncated, info = e.step(NOTHING)
    assert terminated is False and truncated is True   # усечение продолжающегося боя
    assert info["rounds"] == 1 and isinstance(nxt, dict)
    assert reward == pytest.approx(0.0, abs=1e-6)      # за усечение терминальной награды нет


def test_death_is_terminal_with_death_penalty():
    e = FightEnv(rounds_cap=8, clear_bonus=1.0, death_penalty=-1.0)
    e.reset(_fight_scene(foe_hp=999, hero_hp=1))       # хрупкий герой гибнет от ответного удара
    _nxt, reward, terminated, truncated, info = e.step(NOTHING)
    assert terminated is True and truncated is False
    assert info["survived"] is False and info["cleared"] is False
    assert reward == pytest.approx(-1.0, abs=1e-6)      # терминальная награда = death_penalty


# ------------------------------------------------------------------ потенциал: чистая функция
def test_shape_reward_potential_form_and_terminal_zero():
    # non-terminal: только shaping gamma*Phi(s')-Phi(s), исхода боя нет
    mid = shape_reward(0.0, phi_s=2.0, phi_next=3.0, terminated=False, gamma=0.5)
    assert mid == pytest.approx(0.5 * 3.0 - 2.0, abs=1e-6)
    # terminal: Phi(next) принудительно 0, поэтому phi_next проигнорирован
    term = shape_reward(1.0, phi_s=2.0, phi_next=3.0, terminated=True, gamma=0.5)
    assert term == pytest.approx(1.0 - 2.0, abs=1e-6)


def test_phi_terminal_is_zero_in_env():
    # замороженный Phi константен, но на терминале next-потенциал обязан стать 0
    e = FightEnv(rounds_cap=8, phi=lambda obs: 5.0)
    e.reset(_fight_scene(foe_hp=1))
    assert e.phi_s == pytest.approx(5.0)               # Phi(s0) посчитан
    _n, _r, terminated, _tr, info = e.step(ATTACK)
    assert terminated is True
    assert info["phi_next"] == pytest.approx(0.0)       # Phi(terminal)=0


def _shaping_sum(phi_path, gamma=1.0):
    """Σ shaping по траектории: все шаги не-терминальны, кроме последнего (в терминал)."""
    total = 0.0
    for i in range(len(phi_path) - 1):
        last = (i == len(phi_path) - 2)
        total += shape_reward(0.0, phi_path[i], phi_path[i + 1], last, gamma)
    return total


def test_shaping_sum_is_telescoping_invariant_for_same_start():
    # gamma=1, Phi(terminal)=0: сумма shaping = -Phi(s0), не зависит от промежуточных состояний
    a = _shaping_sum([2.0, 1.0, 3.0, 0.0])
    b = _shaping_sum([2.0, 5.0, 5.0, 0.5, 0.0])
    assert a == pytest.approx(-2.0, abs=1e-6)
    assert a == pytest.approx(b, abs=1e-6)              # инвариант: путь не важен


def test_legalize_drops_unreachable_attack_to_no_attack_slot():
    e = FightEnv(rounds_cap=8)
    e.reset(_far_scene())
    legal = e.legalize({"cell": 0, "target": 0, "weapon": 0})   # цель вне дистанции ближнего боя
    assert legal["cell"] == 0 and legal["target"] == 0
    assert legal["weapon"] == NONE_INDEX                 # атака нелегальна -> оружие убрано
    # «не атаковать» legalize не трогает: нечего валидировать
    passthrough = e.legalize({"cell": 0, "target": -1, "weapon": -1})
    assert passthrough == {"cell": 0, "target": -1, "weapon": -1}


def test_step_returns_executed_action_in_info():
    e = FightEnv(rounds_cap=8)
    e.reset(_far_scene())
    _nxt, _r, _term, _trunc, info = e.step(ATTACK)      # proposed ATTACK недопустим целиком
    assert info["action"]["weapon"] == NONE_INDEX        # в info — ИСПОЛНЕННОЕ (легализованное)
