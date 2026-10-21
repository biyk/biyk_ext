# tests/test_arent_polyactor_env.py — WP3: полиакторная среда (инициативный обход).
#
# Новый контракт RL-контура: один шаг = ход ОДНОГО актёра по инициативе (любой стороны),
# затем среда сама переходит к следующему живому. Враги ходят через тот же env.step
# (self-play для политики), а не только жадным foes_act: мон actor-эвристика остаётся
# опциональным legacy-бейзлайном (FightEnv), но основным путём сбора данных становится
# PolyFightEnv. Терминал — «у команды нет живых», а не «умер герой». Актёр бьёт СВОИМ
# per-token оружием (apply_actor + context_for, WP2).
from dataclasses import replace

import pytest

from arent.env import NONE_INDEX
from arent.polyenv import PolyFightEnv
from arent.rollout import RlConfig, _make_env
from arent.team_reward import TeamReward
from conftest import make_npc, make_scene_payload, make_weapon
from planner.context import BattleContext
from planner.points import tuning
from planner.sim import Simulation

# Сцена 2 на 2 с явной инициативой: порядок A1(20) -> F1(15) -> F2(10) -> A2(5).
# F1 стоит вплотную к A1 (свой меч 5ft), F2 — в 5 клетках от A2 со своим луком 30ft;
# базовое оружие сцены — короткий меч (1 клетка): без per-token поиска F2 не достанет.


def _scene(a1_hp=30, a2_hp=30, f1_hp=30, f2_hp=30):
    a1 = make_npc("A1", 0, 0, disposition=-1, hp=a1_hp, speed=30, initiative=20)
    a2 = make_npc("A2", 100, 0, disposition=-1, hp=a2_hp, speed=30, initiative=5)
    f1 = make_npc("F1", 50, 0, disposition=1, hp=f1_hp, speed=30, initiative=15)
    f1["weapons"] = [make_weapon("fsword", "клик. меч", damage="1d6", sure_ft=5)]
    f2 = make_npc("F2", 350, 0, disposition=1, hp=f2_hp, speed=30, initiative=10)
    f2["weapons"] = [make_weapon("fbow", "лук", damage="1d8", sure_ft=30, doubt_ft=120)]
    payload = make_scene_payload(npcs=[a1, a2, f1, f2],
                                 weapons=[make_weapon("sword", damage="1d6+2")])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


NOTHING = {"cell": 0, "target": -1, "weapon": -1}
ATTACK = {"cell": 0, "target": 0, "weapon": 0}


def _env(team=None):
    e = PolyFightEnv(rounds_cap=20, team=team)
    e.reset(_scene())
    return e


#--- 1. обход: курсор хода идёт по инициативе обеих сторон --------------------
def test_reset_tops_initiative_as_first_actor():
    e = _env()
    assert e.actor == "A1"                              # 20 — высшая инициатива, не «герой по праву»


def test_cursor_walks_both_sides_and_wraps_round():
    e = _env(team=TeamReward(draw_window=99))           # пат не мешал бы счёту раундов
    seen = [e.actor]
    for _ in range(4):
        _n, _r, _t, _tr, info = e.step(NOTHING)
        seen.append(e.actor)
        last = info
    assert seen == ["A1", "F1", "F2", "A2", "A1"]       # обе стороны, порядок инициативы
    assert last["rounds"] == 1                          # раунд закрыт полным циклом
    assert last["actor"] == "A2"                        # info несёт актёра, который ходил


def test_step_does_not_counter_like_foes_act():
    e = _env()
    before = {uid: u.hp for uid, u in e.state.units.items()}
    e.step(NOTHING)                                     # ход A1: никто не отвечает сверх действия
    assert {uid: u.hp for uid, u in e.state.units.items()} == before


#--- 2. актёры обеих сторон реально наносят урон через step -------------------
def test_enemy_actor_damage_lands_on_our_unit():
    e = _env(team=TeamReward(draw_window=99))
    e.step(NOTHING)                                     # A1; курсор на F1
    assert e.actor == "F1"
    e.step(ATTACK)                                      # F1 бьёт слотом 0 — ближайшего нашего (A1)
    assert e.state.units["A1"].hp < 30


def test_actor_attacks_with_its_own_per_token_weapon():
    """F2 (лук 30ft) достает A2 за 5 клеток: без per-token поиска оружия удар не прошёл бы."""
    e = _env(team=TeamReward(draw_window=99))
    e.step(NOTHING)                                     # A1
    e.step(NOTHING)                                     # F1
    assert e.actor == "F2"
    before = e.state.units["A2"].hp
    _n, _r, _t, _tr, info = e.step(ATTACK)              # слот цели 0 = ближайший к F2 (A2)
    assert info["action"]["weapon"] != NONE_INDEX
    assert e.state.units["A2"].hp < before
    bow_hit = 4.5 * tuning().hit_chance                 # 1d8 -> ожидание 4.5, попадание общим шансом
    assert before - e.state.units["A2"].hp == pytest.approx(bow_hit, abs=1e-6)


#--- 3. терминал по живым команды, а не по смерти якоря -----------------------
def test_anchor_death_alone_is_not_terminal_when_team_lives():
    e = _env(team=TeamReward(draw_window=99))
    e.step(NOTHING)                                     # A1 сходил
    e.state.units["A1"] = replace(e.state.units["A1"], hp=0.0)   # якорь «герой» погиб
    _n, _r, terminated, _tr, info = e.step(NOTHING)     # F1
    assert terminated is False and info["outcome"] is None       # команда жива (A2) — бой идёт


def test_team_wipe_is_terminal_loss_even_without_hero_on_field():
    e = _env(team=TeamReward(draw_window=99))
    for _ in range(2):                                  # A1, F1
        e.step(NOTHING)
    for uid in ("A1", "A2"):                            # вычистили ВСЮ нашу сторону
        e.state.units[uid] = replace(e.state.units[uid], hp=0.0)
    _n, _r, terminated, _tr, info = e.step(NOTHING)     # ход F2 -> терминал loss по живым
    assert terminated is True and info["outcome"] == "loss"


def test_foe_team_wipe_is_terminal_win():
    e = _env(team=TeamReward(draw_window=99))
    for _ in range(3):                                  # A1, F1, F2
        e.step(NOTHING)
    for uid in ("F1", "F2"):
        e.state.units[uid] = replace(e.state.units[uid], hp=0.0)
    _n, _r, terminated, _tr, info = e.step(ATTACK)      # A2 доходит — врагов нет: win
    assert terminated is True and info["outcome"] == "win"


#--- 4. применение оружия произвольным актёром на уровне Simulation ------------
def test_apply_actor_uses_actor_gear_from_its_own_entry():
    sim = Simulation.of(BattleContext.from_payload(_scene()))
    after = sim.apply_actor("F2", [])                   # без действий — только срез снаряжения
    ctx = after.context_for("F2")
    assert {w.id for w in ctx.weapons} == {"fbow"}


#--- 5. rollout переключается на полиакторную среду по умолчанию --------------
def test_rollout_config_defaults_to_polyactor_and_builds_that_env():
    cfg = RlConfig()
    assert cfg.polyactor is True
    made = _make_env(cfg, TeamReward())
    assert isinstance(made, PolyFightEnv)


def test_rollout_can_still_pick_legacy_monactor_baseline():
    cfg = RlConfig(polyactor=False)                     # A/B: эвристический оппонент остаётся
    from arent.env import FightEnv
    assert isinstance(_make_env(cfg, None), FightEnv)


#--- 6. детерминизм: один и тот же вход -> та же последовательность актёров ----
def test_polyactor_traversal_is_deterministic():
    def trace():
        e = _env(team=TeamReward(draw_window=99))
        seen = []
        for _ in range(6):
            _n, _r, terminated, _tr, _i = e.step(ATTACK)
            seen.append(_i["actor"])
            if terminated:
                break
        return seen, {uid: round(u.hp, 6) for uid, u in e.state.units.items()}
    assert trace() == trace()
