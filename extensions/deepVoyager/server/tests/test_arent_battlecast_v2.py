# tests/test_arent_battlecast_v2.py — Фаза B: усиленный battlecast (battlecast_v2).
#
# Честный контракт v2 (без правок базового battlecast):
#  1. Реестр: battlecast_v2 зарегистрирован и является ПОДКЛАССОМ BattlecastTeacher.
#  2. Базовый battlecast нетронут: реестр "battlecast" по-прежнему указывает ровно на
#     BattlecastTeacher (v2 не подменяет штатного учителя — регрессия чекпойнтов безопасна).
#  3. Якорь регрессии: при margin -> +inf v2 обязан выдавать РОВНО план базового battlecast
#     (переключения нет), т.е. v2 — надстройка над прежней политикой, а не новая развязка.
#  4. Полный набор кандидатов: v2 оценивает исходом (rollout) и атакующие линии по клеткам,
#     и линию манёвра (если предметы-манёвры есть) — иначе манёвр теряется (ошибка прототипа).
#  5. Легальность и детерминизм плана; value лежит на НАШЕЙ шкале (rollout), как у базы.
import math

import pytest

from arent.battlecast import BattlecastTeacher
from arent.battlecast_v2 import BattlecastV2Teacher
from arent.observe import observe
from arent.teacher import pinned
from arent.teachers import get_teacher, list_teachers
from playground.arena import load_arena
from planner.action import ACTION_MOVE, ACTION_TARGET, ACTION_USE
from planner.context import BattleContext
from planner.explore import reachable_paths
from planner.geometry import apply_moves, DIR_VECTORS
from planner.pathfinding import PathfindingService
from planner.turns import rollout
from conftest import make_npc, make_scene_payload, make_weapon

DASH = {"id": "dash_item", "kind": "dash", "name": "Рывок"}
DISENGAGE = {"id": "disengage_item", "kind": "disengage", "name": "Отступление"}
DODGE = {"id": "dodge_item", "kind": "dodge", "name": "Уклонение"}
ALL_M = [DASH, DISENGAGE, DODGE]


def _corridor():
    return load_arena("corridor_archer")


# ───────────────────────────────────────────── 1/2. реестр и нетронутость базы
def test_battlecast_v2_is_registered_subclass():
    assert "battlecast_v2" in list_teachers()
    impl = get_teacher("battlecast_v2", rounds=1, time_limit_sec=0.5)
    assert isinstance(impl, BattlecastV2Teacher)
    assert isinstance(impl, BattlecastTeacher)      # подкласс — наследует всю базу


def test_base_battlecast_registry_untouched():
    """v2 НЕ подменяет штатного учителя: battlecast остаётся ровно BattlecastTeacher."""
    assert get_teacher("battlecast", rounds=1).__class__ is BattlecastTeacher
    assert BattlecastV2Teacher is not BattlecastTeacher
    # v2 — надстройка: наследует choose() базы (тот же эвристи-аргмас), меняет лишь развязку
    assert BattlecastV2Teacher.choose is BattlecastTeacher.choose      # choose не переопределён
    assert BattlecastV2Teacher._actions is not BattlecastTeacher._actions  # только развязка


# ───────────────────────────────────────────── 3. якорь: margin=inf => план базы
def test_v2_with_infinite_margin_equals_base_battlecast():
    payload = _corridor()
    ctx = BattleContext.from_payload(payload)
    base = BattlecastTeacher(rounds=1)
    v2 = BattlecastV2Teacher(rounds=1, margin=math.inf)   # переключений никогда
    with pinned(rounds=1, time_limit_sec=0.5):
        a_base = base.plan(ctx)
        a_v2 = v2.plan(BattleContext.from_payload(payload))
    assert [x.to_dict() for x in a_v2] == [x.to_dict() for x in a_base]


# ───────────────────────────────────────────── 4. полный набор кандидатов (с манёвром)
def _melee_ctx_with_maneuvers():
    a = make_npc("A", 0, 0, disposition=-1, hp=40)
    f = make_npc("F", 1 * 50, 0, disposition=1, hp=40, damage="2d6")   # смежная клетка
    p = make_scene_payload(npcs=[a, f], weapons=[make_weapon("sw", damage="1d8+2", sure_ft=5)],
                           token="F")
    p.update({"src": "A", "speed": 30, "maneuvers": ALL_M})
    return BattleContext.from_payload(p)


def test_v2_candidates_include_a_maneuver_line_when_items_present():
    """Ключевой fix против прототипа: линия манёвра обязана быть среди оцениваемых кандидатов."""
    ctx = _melee_ctx_with_maneuvers()
    v2 = BattlecastV2Teacher(rounds=1)
    obs = observe(ctx)
    lines = v2._candidate_lines(ctx, obs)
    assert lines, "кандидаты не должны быть пустыми при живых врагах и оружии"
    maneuver_ids = {m["id"] for m in ALL_M}
    used_maneuver = any(any(x.action == ACTION_USE and x.conf["itemId"] in maneuver_ids
                            for x in line) for line in lines)
    assert used_maneuver, "ни одна кандидатная линия не использует предмет-манёвр"


def test_v2_candidates_are_all_legal_nonempty_lines():
    ctx = _melee_ctx_with_maneuvers()
    v2 = BattlecastV2Teacher(rounds=1)
    obs = observe(ctx)
    hostiles = {t.id for t in ctx.hostile_targets()}
    weapons = {w.id for w in ctx.weapons}
    maneuver_ids = {m["id"] for m in ALL_M}
    for line in v2._candidate_lines(ctx, obs):
        assert line
        dirs = [x.conf["direction"] for x in line if x.action == ACTION_MOVE]
        assert all(d in DIR_VECTORS for d in dirs)      # все перемещения — штатные направления
        for x in line:
            if x.action == ACTION_TARGET:
                assert x.conf["id"] in hostiles
            if x.action == ACTION_USE:
                # оружие в атакующей линии ИЛИ предмет-манёвр (dash честно выходит за шаг)
                assert x.conf["itemId"] in (weapons | maneuver_ids)


# ───────────────────────────────────────────── 5. легальность/детерминизм/value
def test_v2_chosen_actions_pass_our_legality_check():
    payload = _corridor()
    v2 = BattlecastV2Teacher(rounds=1, time_limit_sec=0.5)
    ctx = BattleContext.from_payload(payload)
    labeled_actions = v2.plan(ctx)
    hostiles = {t.id for t in ctx.hostile_targets()}
    weapons = {w.id for w in ctx.weapons}
    pf = PathfindingService(ctx)._finder
    paths = reachable_paths(pf, ctx.src_cell, ctx.src_id, ctx.speed_steps)
    dirs = [a.conf["direction"] for a in labeled_actions if a.action == ACTION_MOVE]
    assert all(d in DIR_VECTORS for d in dirs)
    final = apply_moves(ctx.src_cell, dirs)
    assert final in paths
    for a in labeled_actions:
        if a.action == ACTION_TARGET:
            assert a.conf["id"] in hostiles
        if a.action == ACTION_USE:
            assert a.conf["itemId"] in weapons


def test_v2_plan_is_deterministic():
    payload = _corridor()
    v2 = BattlecastV2Teacher(rounds=1, time_limit_sec=0.5)
    with pinned(rounds=1, time_limit_sec=0.5):
        first = [a.to_dict() for a in v2.plan(BattleContext.from_payload(payload))]
        second = [a.to_dict() for a in v2.plan(BattleContext.from_payload(payload))]
    assert first == second


def test_v2_value_is_our_rollout_scale():
    payload = _corridor()
    v2 = BattlecastV2Teacher(rounds=1, time_limit_sec=0.5)
    with pinned(rounds=1, time_limit_sec=0.5):
        labeled = v2.label(payload)
    expected = rollout(labeled.ctx, labeled.actions, v2.value_rounds)
    assert labeled.value == pytest.approx(expected)


# ───────────────────────────────────────────── back-compat: без манёвров — только атака
def test_v2_without_maneuver_items_is_attack_only():
    a = make_npc("A", 0, 0, disposition=-1, hp=40)
    f = make_npc("F", 1 * 50, 0, disposition=1, hp=40, damage="1d8")
    p = make_scene_payload(npcs=[a, f], weapons=[make_weapon("sw", damage="1d8+2", sure_ft=5)],
                           token="F")
    p.update({"src": "A", "speed": 30})   # maneuvers нет (v2/v3/v4)
    ctx = BattleContext.from_payload(p)
    v2 = BattlecastV2Teacher(rounds=1)
    actions = v2.plan(ctx)
    used = {x.conf["itemId"] for x in actions if x.action == ACTION_USE}
    assert used <= {"sw"}                       # только оружие, никакого манёвра
    assert any(x.action == ACTION_TARGET for x in actions)
