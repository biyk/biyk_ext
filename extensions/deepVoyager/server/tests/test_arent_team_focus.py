# tests/test_arent_team_focus.py — Фаза C/D: `wesnoth_focusfire` (командный залп).
#
# План честно откладывал этот пункт: одиночный `plan(ctx)` размечает ОДНОГО актёра, поэтому
# «focus-fire» в нём был бы переименованным battlecast. Но у нас есть полиакторный контур:
# `team_eval.TeacherController` живёт ВЕСЬ бой и вызывается по очереди за каждого союзника.
# Значит координация места — уровень КОМАНДЫ (контроллер), а не одиночного учителя:
#  • `team_focus_target(ctx)` — чистая функция: выбирает цель, которую команда способна
#    добить в этом раунде (суммарный EV урона всех живых союзников >= hp), иначе самую
#    опасную. Так «залп» опирается на силы СОЮЗНИКОВ, а не на EV одного стрелка.
#  • `WesnothFocusFireTeacher` — stateless-учитель: при preferred_target=None побитово равен
#    battlecast; с целью — бьёт её, если она достижима, иначе честный фолбэк на базу.
#  • `TeamFocusController` — общий на раунд план: все союзники получают одну цель; новый
#    раунд/новая битва пересчитывают план (детерминированно, без утечки между боями).
import pytest

from arent.battlecast import BattlecastTeacher
from arent.observe import observe
from arent import slots_v3
from arent import spec3
from arent.team_eval import build_controller
from arent.team_focus import (TeamFocusController, WesnothFocusFireTeacher,
                              team_damage_on, team_focus_target)
from arent.teachers import list_teachers
from conftest import make_npc, make_scene_payload, make_weapon
from planner.action import ACTION_TARGET
from planner.context import BattleContext


SWORD = make_weapon("sw", damage="2d6+2", bonus=5, sure_ft=5, doubt_ft=5)


def _unit(nid, x, disp, ini, hp, *, weapons=None, damage="1d4", hit_chance=0.65,
          ac=12, reach_ft=None):
    n = make_npc(nid, x, 0, disposition=disp, hp=hp, speed=30, initiative=ini,
                 damage=damage, hit_chance=hit_chance, reach_ft=reach_ft)
    n["ac"] = ac
    if weapons is not None:
        n["weapons"] = weapons
    return n


def _ctx(actor="A", enemies=None):
    """A (0,0) и C (300,0) против E1 (50,0, hp=10) и E2 (400,0, hp=40, низкий КД).

    E1 достижим обоими (A рядом, C за 5 клеток при ходе 6), но никем не добивается в
    одиночку: EV ~6.3 < 10, а вдвоём ~12.6 >= 10. E2 достаёт только C, и лично ему он
    «вкуснее» по EV (низкий КД -> шанс попадания 100%), но командой не добивается.
    """
    enemies = enemies or [
        _unit("E1", 50, 1, 15, 10, damage="3d6", hit_chance=0.8, reach_ft=5, ac=12),
        _unit("E2", 400, 1, 5, 40, damage="1d4", hit_chance=0.5, reach_ft=5, ac=5),
    ]
    npcs = [_unit("A", 0, -1, 20, 30, weapons=[SWORD]),
            _unit("C", 300, -1, 10, 30, weapons=[SWORD])] + enemies
    payload = make_scene_payload(npcs=npcs, weapons=[SWORD], token="E1")
    payload.update({"src": actor, "speed": 30})
    return BattleContext.from_payload(payload)


def _plan_of(controller, ctx):
    """Прогнать контроллер как среда: obs+slots -> label -> действия."""
    obs = observe(ctx, ("A", "E1", "C", "E2"), ctx.src_id)
    slots = slots_v3.build(ctx, obs)
    label = controller.label(obs, ctx, slots)
    return slots_v3.decode(slots, label)


def _aim(actions):
    return next((a.conf.get("id") for a in actions if a.action == ACTION_TARGET), None)


# --- чистая функция: кого способна добить КОМАНДА ---------------------------

def test_team_focus_target_picks_the_enemy_team_can_kill_together():
    ctx = _ctx()
    e1 = ctx.token("E1")
    allies = [ctx.token("A"), ctx.token("C")]
    solo = max(team_damage_on(ctx, [a], e1) for a in allies)
    team = team_damage_on(ctx, allies, e1)
    assert solo < e1.hp_current <= team             # никто один, но вдвоём — добиваем
    assert team_focus_target(ctx) == "E1"


def test_team_focus_target_falls_back_to_most_dangerous_when_nothing_killable():
    enemies = [_unit("E1", 50, 1, 15, 100, damage="1d4", hit_chance=0.4, reach_ft=5),
               _unit("E2", 400, 1, 5, 100, damage="2d6", hit_chance=0.8, reach_ft=5)]
    assert team_focus_target(_ctx(enemies=enemies)) == "E2"


def test_team_focus_target_is_empty_without_enemies():
    npcs = [_unit("A", 0, -1, 20, 30, weapons=[SWORD]),
            _unit("C", 300, -1, 10, 30, weapons=[SWORD]),
            _unit("N", 50, 0, 15, 10)]                     # нейтральный — не враг
    payload = make_scene_payload(npcs=npcs, weapons=[SWORD], token="A")
    payload.update({"src": "A", "speed": 30})
    assert team_focus_target(BattleContext.from_payload(payload)) is None


# --- учитель: якорь на battlecast, цель — только если достижима --------------

def test_focus_teacher_without_preference_is_bitwise_battlecast():
    ctx = _ctx(actor="C")
    base = BattlecastTeacher(rounds=1).plan(ctx)
    focus = WesnothFocusFireTeacher(rounds=1).plan(ctx)
    assert [(a.action, dict(a.conf)) for a in focus] == [(a.action, dict(a.conf)) for a in base]


def test_focus_teacher_hits_the_preferred_target_when_reachable():
    ctx = _ctx(actor="C")
    assert _aim(BattlecastTeacher(rounds=1).plan(ctx)) == "E2"   # база раскрывается на опасного
    teacher = WesnothFocusFireTeacher(rounds=1)
    teacher.preferred_target = "E1"
    assert _aim(teacher.plan(ctx)) == "E1"                        # залп важнее личной выгоды


def test_focus_teacher_falls_back_to_base_when_target_unreachable():
    ctx = _ctx(actor="A")                                        # A не достаёт E2
    teacher = WesnothFocusFireTeacher(rounds=1)
    teacher.preferred_target = "E2"
    base = BattlecastTeacher(rounds=1).plan(ctx)
    assert [(a.action, dict(a.conf)) for a in teacher.plan(ctx)] == \
           [(a.action, dict(a.conf)) for a in base]


# --- контроллер: общий план на раунд, пересчёт, изоляция боёв ----------------

def test_controller_makes_both_allies_focus_the_same_target():
    controller = TeamFocusController(schema=spec3.SCHEMA)
    first = _aim(_plan_of(controller, _ctx(actor="A")))
    second = _aim(_plan_of(controller, _ctx(actor="C")))
    assert first == second == "E1"                    # оба бьют одну цель (залп)
    # а без координации второй союзник пошёл бы в опасного E2:
    assert _aim(BattlecastTeacher(rounds=1).plan(_ctx(actor="C"))) == "E2"


def test_controller_replans_when_focus_target_dies_mid_round():
    controller = TeamFocusController(schema=spec3.SCHEMA)
    _plan_of(controller, _ctx(actor="A"))
    assert controller.preferred_target == "E1"
    hurt = _ctx(actor="C", enemies=[
        _unit("E1", 50, 1, 15, 0, reach_ft=5),        # добит союзником
        _unit("E2", 400, 1, 5, 40, damage="3d6", hit_chance=0.8, reach_ft=5)])
    _plan_of(controller, hurt)
    assert controller.preferred_target == "E2"        # мёртвую цель не держим


def test_controller_starts_a_new_round_when_an_actor_repeats():
    controller = TeamFocusController(schema=spec3.SCHEMA)
    _plan_of(controller, _ctx(actor="A"))
    _plan_of(controller, _ctx(actor="C"))
    assert controller.round_seen == ["A", "C"]
    _plan_of(controller, _ctx(actor="A"))             # A снова -> новый раунд
    assert controller.round_seen == ["A"]


def test_controller_resets_state_for_a_new_battle():
    controller = TeamFocusController(schema=spec3.SCHEMA)
    _plan_of(controller, _ctx(actor="A"))
    other = _ctx(enemies=[_unit("X1", 50, 1, 15, 10, reach_ft=5)])
    _plan_of(controller, other)
    assert controller.round_seen == ["A"]             # старый бой не протёк
    assert controller.preferred_target == "X1"


def test_controller_translates_teacher_into_schema_slots():
    controller = TeamFocusController(schema=spec3.SCHEMA)
    actions = _plan_of(controller, _ctx(actor="A"))
    assert _aim(actions) == "E1"
    assert controller.schema == spec3.SCHEMA


# --- реестр/фабрика --------------------------------------------------------

def test_focusfire_is_a_registered_teacher_and_controller():
    assert "wesnoth_focusfire" in list_teachers()
    controller = build_controller("wesnoth_focusfire", spec3.SCHEMA)
    assert isinstance(controller, TeamFocusController)
    assert getattr(controller, "_is_controller", False) is True
