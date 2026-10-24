# tests/test_arent_team_reward.py — командная награда v2 (коммит №4): нормализованная ±5.
#
# Проверяем semantics награды, а не красивые float: исход команды (win/loss/mutual/draw),
# плотные события (убил/попал/живые-враги-пинать) и главное — окно пата: draw_window раундов
# подряд без попаданий/убийств => DRAW (терминал), а не бесконечное усечение. reward_scale
# переводит сырое значение хода в полосу ±5 только когда raw_weight>0 (по умолчанию выкл.).
# Отдельно — интеграция со средой: с TeamReward терминал берётся из исхода команды, а без него
# legacy-путь (одиночный герой) остаётся ровно прежним.
import pytest

from arent.env import FightEnv
from arent.team_reward import (DRAW, HIT, KILL, LIVING_COST, LOSS, REWARD_SCALE, WIN,
                               TeamReward)
from conftest import make_npc, make_scene_payload, make_weapon
from planner.initiative import Unit


def unit(uid, hp, hostile=False, ally=False):
    return Unit(id=uid, cell=(0, 0) if not hostile else (1, 0), hp=float(hp), speed_steps=6,
                damage_avg=5.0, reach_cells=1.0, chance=0.65, hostile_to_hero=hostile,
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
    assert reward == pytest.approx(WIN + KILL + HIT + LIVING_COST * 0, abs=1e-6)


def test_loss_when_own_dead_foes_alive():
    tr = TeamReward()
    nxt = {"A": unit("A", 0), "B": unit("B", 20, hostile=True)}
    reward, outcome = tr.step(_both_alive(), nxt, "A")
    assert outcome == "loss"
    assert reward == pytest.approx(LOSS + LIVING_COST, abs=1e-6)      # один живой враг пинаем


def test_mutual_when_both_sides_wiped():
    tr = TeamReward()
    nxt = {"A": unit("A", 0), "B": unit("B", 0, hostile=True)}
    reward, outcome = tr.step(_both_alive(), nxt, "A")
    assert outcome == "mutual"
    assert reward == pytest.approx(KILL + HIT, abs=1e-6)          # исход 0, но урон-события считаем


def test_alive_both_sides_is_not_terminal():
    tr = TeamReward()
    reward, outcome = tr.step(_both_alive(), _both_alive(), "A")
    assert outcome is None
    assert reward == pytest.approx(LIVING_COST, abs=1e-6)             # без событий, 1 живой враг


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


#--- 3. плотные события и сырой подмес --------------------------------------
def test_kill_credit_counts_enemies_that_died():
    tr = TeamReward()
    prev = {"A": unit("A", 20), "B": unit("B", 1, hostile=True), "C": unit("C", 1, hostile=True)}
    nxt = {"A": unit("A", 20), "B": unit("B", 0, hostile=True), "C": unit("C", 0, hostile=True)}
    reward, outcome = tr.step(prev, nxt, "A")
    assert outcome == "win" and reward == pytest.approx(WIN + 2 * KILL + 2 * HIT, abs=1e-6)


def test_raw_value_scaled_by_reward_scale_only_when_weighted():
    off = TeamReward(raw_weight=0.0).step(_both_alive(), _both_alive(), "A", raw_value=300.0)
    base = TeamReward(raw_weight=0.0).step(_both_alive(), _both_alive(), "A", raw_value=0.0)
    assert off[0] == pytest.approx(base[0], abs=1e-9)                 # выкл: значение не течёт
    on = TeamReward(raw_weight=1.0).step(_both_alive(), _both_alive(), "A", raw_value=300.0)
    assert on[0] - base[0] == pytest.approx(300.0 / REWARD_SCALE, abs=1e-6)


def test_to_dict_exposes_scale_and_points():
    d = TeamReward().to_dict()
    assert d["reward_scale"] == REWARD_SCALE and d["r_win"] == WIN and d["r_loss"] == LOSS
    assert d["r_draw"] == DRAW


#--- единое место управления: числа базы приходят извне (points.json tactics.base) --- #
def test_from_base_empty_equals_defaults():
    assert TeamReward.from_base().points == TeamReward().points


def test_from_base_overrides_numbers():
    tr = TeamReward.from_base(base={"win": 7.0, "kill": 0.25})
    nxt = {"A": unit("A", 20), "B": unit("B", 0, hostile=True)}
    reward, outcome = tr.step(_both_alive(), nxt, "A")
    assert outcome == "win"
    assert reward == pytest.approx(7.0 + 0.25 + HIT + 0.0, abs=1e-6)   # исход 7, убийство 0.25


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
