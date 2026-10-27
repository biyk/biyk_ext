# tests/test_arent_team_reward.py — v3: награда по ВЕЛИЧИНЕ нанесённого урона.
#
# Основная цель — наносить урон (dealt_hp * coef+), полученный = штраф (taken_hp * 0.9).
# Победа абсолютна (+50), убийство побочная (+5), поражение/ничья/взаимное = 0.
import pytest

from arent.env import FightEnv
from arent.team_reward import (DRAW, DAMAGE_DEALT, DAMAGE_TAKEN, KILL, LOSS,
                               REWARD_SCALE, WIN, TeamReward)
from conftest import make_npc, make_scene_payload, make_weapon
from planner.initiative import Unit


def unit(uid, hp, hostile=False, ally=False, reach=1.0):
    return Unit(id=uid, cell=(0, 0) if not hostile else (1, 0), hp=float(hp), speed_steps=6,
                damage_avg=5.0, reach_cells=float(reach), chance=0.65, hostile_to_hero=hostile,
                ally_to_hero=ally)


def _both_alive():
    return {"A": unit("A", 20), "B": unit("B", 20, hostile=True)}


#--- 1. исход команды ---------------------------------------------------------
def test_win_when_all_foes_dead_and_own_alive():
    tr = TeamReward()
    prev = _both_alive()
    nxt = {"A": unit("A", 20), "B": unit("B", 0, hostile=True)}
    reward, outcome = tr.step(prev, nxt, "A")
    assert outcome == "win"
    # dealt 20 HP, kill 1, win terminal: KILL + DAMAGE_DEALT*20 + WIN
    assert reward == pytest.approx(WIN + KILL + DAMAGE_DEALT * 20, abs=1e-6)


def test_loss_when_own_dead_foes_alive():
    tr = TeamReward()
    nxt = {"A": unit("A", 0), "B": unit("B", 20, hostile=True)}
    reward, outcome = tr.step(_both_alive(), nxt, "A")
    assert outcome == "loss"
    # taken 20 HP -> penalty -DAMAGE_TAKEN*20; LOSS = 0 (смерть не штраф)
    assert reward == pytest.approx(-DAMAGE_TAKEN * 20 + LOSS, abs=1e-6)


def test_mutual_when_both_sides_wiped():
    tr = TeamReward()
    nxt = {"A": unit("A", 0), "B": unit("B", 0, hostile=True)}
    reward, outcome = tr.step(_both_alive(), nxt, "A")
    assert outcome == "mutual"
    # dealt=20 + taken=20, kill=1, MUTUAL=0
    assert reward == pytest.approx(KILL + DAMAGE_DEALT * 20 - DAMAGE_TAKEN * 20, abs=1e-6)


def test_alive_both_sides_is_not_terminal():
    tr = TeamReward()
    reward, outcome = tr.step(_both_alive(), _both_alive(), "A")
    assert outcome is None
    assert reward == pytest.approx(0.0, abs=1e-6)   # без урона и событий — ноль


def test_reward_is_proportional_to_damage_dealt():
    tr = TeamReward()
    hit = {"A": unit("A", 20), "B": unit("B", 12, hostile=True)}      # снято 8 HP
    reward, outcome = tr.step(_both_alive(), hit, "A")
    assert outcome is None
    assert reward == pytest.approx(DAMAGE_DEALT * 8, abs=1e-6)


def test_reward_penalizes_damage_taken_softer_than_dealt():
    tr = TeamReward()
    hurt = {"A": unit("A", 12), "B": unit("B", 20, hostile=True)}     # потеряно 8 HP
    reward, outcome = tr.step(_both_alive(), hurt, "A")
    assert outcome is None
    assert reward == pytest.approx(-DAMAGE_TAKEN * 8, abs=1e-6)


def test_symmetric_trade_net_is_dealt_minus_softened_taken():
    tr = TeamReward()
    nxt = {"A": unit("A", 15), "B": unit("B", 12, hostile=True)}      # dealt 8, taken 5
    reward, _o = tr.step(_both_alive(), nxt, "A")
    assert reward == pytest.approx(DAMAGE_DEALT * 8 - DAMAGE_TAKEN * 5, abs=1e-6)


#--- 2. окно пата: раунды без событий => DRAW -------------------------------
def test_draw_fires_after_window_of_quiet_rounds():
    tr = TeamReward(draw_window=3)
    outcomes = [tr.step(_both_alive(), _both_alive(), "A")[1] for _ in range(3)]
    assert outcomes[:2] == [None, None] and outcomes[2] == "draw"


def test_event_resets_stall_so_no_draw():
    tr = TeamReward(draw_window=2)
    tr.step(_both_alive(), _both_alive(), "A")                        # 1-й тихий
    hit = {"A": unit("A", 20), "B": unit("B", 10, hostile=True)}      # попал -> событие
    _r, outcome = tr.step(_both_alive(), hit, "A")
    assert outcome is None                                            # пат сброшен попаданием


def test_reset_clears_the_stall_window():
    tr = TeamReward(draw_window=2)
    tr.step(_both_alive(), _both_alive(), "A")
    tr.reset()
    assert tr.step(_both_alive(), _both_alive(), "A")[1] is None      # окно снова пустое


#--- 2b. победа по очкам: таймаут(cap) и пат судим по разнице урона -----------
def test_cap_with_more_damage_dealt_is_win():
    # арчер чипит танка (нанёс 10, не получил) и доживает до cap никто не уничтожен -> WIN по очкам
    tr = TeamReward()
    hit = {"A": unit("A", 20), "B": unit("B", 10, hostile=True)}   # dealt 10, taken 0
    _r, outcome = tr.step(_both_alive(), hit, "A")
    assert outcome is None                                          # оба живы — бой идёт
    _r, outcome = tr.step(hit, hit, "A", at_cap=True)              # cap, урона больше нет
    assert outcome == "win"


def test_cap_with_more_damage_taken_is_loss():
    tr = TeamReward()
    hurt = {"A": unit("A", 10), "B": unit("B", 20, hostile=True)}   # taken 10, dealt 0
    tr.step(_both_alive(), hurt, "A")
    _r, outcome = tr.step(hurt, hurt, "A", at_cap=True)
    assert outcome == "loss"


def test_cap_equal_damage_tie_break_gives_winnner_to_hunted_ranged():
    # безуронная глухая ничья: у кого дальность больше (дальник, «кого гоняли») — тот и победил
    tr = TeamReward()
    a = unit("A", 20, reach=5.0)                                     # дальник (рогатка)
    b = unit("B", 20, hostile=True, reach=1.0)                      # мили-танк
    _r, outcome = tr.step({"A": a, "B": b}, {"A": a, "B": b}, "A", at_cap=True)
    assert outcome == "win"                                         # очки равны (0), ничья по reach -> our win


def test_cap_equal_damage_and_reach_is_draw():
    tr = TeamReward()
    _r, outcome = tr.step(_both_alive(), _both_alive(), "A", at_cap=True)   # оба reach1, урона нет
    assert outcome == "draw"


def test_stall_is_judged_by_points_not_blanket_draw():
    # накопил преимущество по урону, затем draw_window тихих раундов -> победа по очкам, не −4 ничья
    tr = TeamReward(draw_window=2)
    hit = {"A": unit("A", 20), "B": unit("B", 10, hostile=True)}
    tr.step(_both_alive(), hit, "A", tick=True)                     # событие: +5 dealt
    tr.step(hit, hit, "A", tick=True)                               # тихий 1
    _r, outcome = tr.step(hit, hit, "A", tick=True)                # тихий 2 -> окно заполнено
    assert outcome == "win"                                         # очки +10 -> win вместо draw


#--- 3. плотные события и сырой подмес --------------------------------------
def test_kill_credit_counts_enemies_that_died():
    tr = TeamReward()
    prev = {"A": unit("A", 20), "B": unit("B", 1, hostile=True), "C": unit("C", 1, hostile=True)}
    nxt = {"A": unit("A", 20), "B": unit("B", 0, hostile=True), "C": unit("C", 0, hostile=True)}
    reward, outcome = tr.step(prev, nxt, "A")
    # kills 2, dealt = 1+1 = 2 HP
    assert outcome == "win" and reward == pytest.approx(WIN + 2 * KILL + DAMAGE_DEALT * 2, abs=1e-6)


def test_raw_value_scaled_by_reward_scale_only_when_weighted():
    off = TeamReward(raw_weight=0.0).step(_both_alive(), _both_alive(), "A", raw_value=300.0)
    base = TeamReward(raw_weight=0.0).step(_both_alive(), _both_alive(), "A", raw_value=0.0)
    assert off[0] == pytest.approx(base[0], abs=1e-9)                 # выкл: значение не течёт
    on = TeamReward(raw_weight=1.0).step(_both_alive(), _both_alive(), "A", raw_value=300.0)
    assert on[0] - base[0] == pytest.approx(300.0 / REWARD_SCALE, abs=1e-6)


def test_to_dict_exposes_scale_and_points():
    d = TeamReward().to_dict()
    assert d["reward_scale"] == REWARD_SCALE and d["r_win"] == WIN and d["r_loss"] == LOSS
    assert d["r_draw"] == DRAW and d["r_damage_dealt"] == DAMAGE_DEALT
    assert d["r_damage_taken"] == DAMAGE_TAKEN


#--- единое место управления: числа базы приходят извне (points.json tactics.base) --- #
def test_from_base_empty_equals_defaults():
    assert TeamReward.from_base().points == TeamReward().points


def test_from_base_overrides_numbers():
    tr = TeamReward.from_base(base={"win": 7.0, "kill": 0.25})
    nxt = {"A": unit("A", 20), "B": unit("B", 0, hostile=True)}
    reward, outcome = tr.step(_both_alive(), nxt, "A")
    assert outcome == "win"
    # dealt 20 HP with default DAMAGE_DEALT (1.0), kill 0.25, win 7.0
    assert reward == pytest.approx(7.0 + 0.25 + DAMAGE_DEALT * 20, abs=1e-6)


def test_from_base_ignores_unknown_keys():
    assert TeamReward.from_base(base={"not_an_event": 9.0}).points == TeamReward().points


#--- 4. интеграция со средой ------------------------------------------------
def _far_scene(hero_hp=50):
    hero = make_npc("A", 0, 0, disposition=-1, hp=hero_hp, speed=30, damage="1d8")
    foe = make_npc("B", 450, 0, disposition=1, hp=999, speed=5, damage="1d8")
    # speed=5ft — клетка за раунд, reachFt=5 — достает только вплотную: до 9 клеток
    # добежит не раньше 9-го раунда, первые раунды честно тихие (пат ловится окном)
    foe["reachFt"] = 5
    return make_scene_payload(npcs=[hero, foe], weapons=[make_weapon("sword", damage="1d6+2")],
                              token="B")


def _fight_scene(foe_hp=1, hero_hp=50):
    hero = make_npc("A", 0, 0, disposition=-1, hp=hero_hp, speed=30, damage="1d8")
    foe = make_npc("B", 50, 0, disposition=1, hp=foe_hp, speed=0, damage="1d8")
    return make_scene_payload(npcs=[hero, foe], weapons=[make_weapon("sword", damage="1d6+2")],
                              token="B")


NOTHING = {"cell": 0, "target": -1, "weapon": -1}
ATTACK = {"cell": 0, "target": 0, "weapon": 0}


def test_env_team_reward_terminal_from_outcome_on_win():
    e = FightEnv(rounds_cap=8, team=TeamReward())
    e.reset(_fight_scene(foe_hp=1))
    _nxt, reward, terminated, _trunc, info = e.step(ATTACK)
    assert terminated is True and info["outcome"] == "win"
    assert reward > 4.0                                                 # исход команды, не ±1 legacy


def test_env_team_reward_detects_stalemate_draw_before_cap():
    e = FightEnv(rounds_cap=20, team=TeamReward(draw_window=4))         # потолок далеко за окном
    e.reset(_far_scene())
    seq = [e.step(NOTHING) for _ in range(4)]
    assert [t for _n, _r, t, _tr, _i in seq[:3]] == [False, False, False]
    _n, _r, terminated, truncated, info = seq[3]
    assert terminated is True and truncated is False and info["outcome"] == "draw"


def test_env_legacy_path_unchanged_without_team():
    e = FightEnv(rounds_cap=8, clear_bonus=1.0, death_penalty=-1.0)     # team=None
    e.reset(_fight_scene(foe_hp=1))
    _n, reward, terminated, _tr, info = e.step(ATTACK)
    assert terminated is True and info.get("outcome") is None
    assert reward == pytest.approx(1.0, abs=1e-6)                        # ровно прежний clear_bonus
