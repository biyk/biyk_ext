# tests/test_arent_ext_styles.py — Фаза C: НОВЫЕ независимые стили-политики (opponent diversity).
#
# Честный контракт (см. search_teacher/PLAN.md, Фаза C): стиль должен быть ПОВЕДЕНЧЕСКИ
# иным, а не battlecast с другими числами. Здесь два по-настоящему отличных стиля:
#  • ufo_style — развязка ПОЛНОГО плана по исходу симуляции (механизм battlecast_v2) с
#    агрессивным профилем угрозы. Отличие от базы — НЕ вес, а способ выбора (оценка
#    исходом rollout над всеми кандидатами), поэтому ufo_style = подкласс BattlecastV2Teacher.
#  • cdda_ranged_support — скирмишер-поддержка: НОВЫЙ член функции ценности (держать
#    дистанцию до ближайшего врага = kiting), а не перевес threat. Якорь keep_distance=0
#    обязан совпадать с базой (доказывает, что отличие вносит ровно новый член).
import pytest

from arent.battlecast import BattlecastTeacher
from arent.battlecast_v2 import BattlecastV2Teacher
from arent.ext_teachers import CddaRangedSupport, UFOStyleTeacher
from arent.observe import observe
from arent.teacher import pinned
from arent.teachers import get_teacher, list_teachers
from playground.arena import load_arena
from planner.context import BattleContext
from planner.geometry import cell_distance
from planner.points import tuning
from planner.turns import rollout
from conftest import make_npc, make_scene_payload


# ───────────────────────────────────────────── 1. реестр и наследование механизма
def test_new_styles_are_registered():
    names = list_teachers()
    for n in ("ufo_style", "cdda_ranged_support"):
        assert n in names, f"{n} не в реестре: {names}"


def test_ufo_style_is_outcome_evaluator_subclass_of_v2():
    """ufo_style отличается СПОСОБОМ развязки (оценка исходом), значит это подкласс v2."""
    impl = get_teacher("ufo_style", rounds=1, time_limit_sec=0.5)
    assert isinstance(impl, UFOStyleTeacher)
    assert isinstance(impl, BattlecastV2Teacher)
    assert hasattr(impl, "_candidate_lines")           # механизм оценки исходом
    # агрессивный профиль: толерантнее к входящему огню, чем дефолт v2 (threat=1.0)
    assert impl.threat < BattlecastV2Teacher(rounds=1).threat


def test_cdda_is_battlecast_subclass_with_distance_term():
    impl = get_teacher("cdda_ranged_support", rounds=1)
    assert isinstance(impl, CddaRangedSupport)
    assert isinstance(impl, BattlecastTeacher)
    assert impl.keep_distance > 0.0                    # скирмишер реально держит дистанцию


# ───────────────────────────────────────────── 2. детерминизм / легальность / value-шкала
def test_ufo_style_plan_is_deterministic_and_legal():
    payload = load_arena("corridor_archer")
    t = get_teacher("ufo_style", rounds=1, time_limit_sec=0.5)
    with pinned(rounds=1, time_limit_sec=0.5):
        first = [a.to_dict() for a in t.plan(BattleContext.from_payload(payload))]
        second = [a.to_dict() for a in t.plan(BattleContext.from_payload(payload))]
    assert first == second and first                  # план существует и стабилен


def test_ufo_style_value_is_our_rollout_scale():
    payload = load_arena("corridor_archer")
    t = get_teacher("ufo_style", rounds=1)
    with pinned(rounds=1, time_limit_sec=0.5):
        labeled = t.label(payload)
    assert labeled.value == pytest.approx(
        rollout(labeled.ctx, labeled.actions, t.value_rounds))


def test_cdda_plan_is_deterministic_and_value_on_rollout_scale():
    payload = load_arena("corridor_archer")
    t = get_teacher("cdda_ranged_support", rounds=1)
    with pinned(rounds=1, time_limit_sec=0.5):
        labeled = t.label(payload)
        again = get_teacher("cdda_ranged_support", rounds=1).label(payload)
    assert [a.to_dict() for a in labeled.actions] == [a.to_dict() for a in again.actions]
    assert labeled.value == pytest.approx(
        rollout(labeled.ctx, labeled.actions, t.value_rounds))


# ───────────────────────────────────────────── 3. поведенческий отличительный признак cdda
def _open_field_no_weapon(speed_cells_src: int):
    """Открытое поле, у героя НЕТ оружия -> выбор клетки чист по позиции (подход vs дистанция).

    Враг на скорости 0 с коротким reach, поэтому из всех достижимых клеток входящий огонь = 0:
    база наступает (максимизирует approach), cdda с keep_distance разворачивает назад.
    """
    a = make_npc("A", 0, 0, disposition=-1, hp=40)                       # клетка (0,0)
    e = make_npc("E", tuning().feet_per_cell * 6, 0, disposition=1,
                 hp=40, speed=0, reach_ft=tuning().feet_per_cell)        # клетка (0,6)
    p = make_scene_payload(npcs=[a, e], weapons=[], token="E")
    p.update({"src": "A", "speed": tuning().feet_per_cell * speed_cells_src})
    return BattleContext.from_payload(p)


def _enemy_cell(ctx):
    return ctx.cell_of(next(iter(ctx.hostile_targets())))


def test_cdda_zero_keep_distance_is_anchor_equal_to_base():
    """keep_distance=0 => choose побитово равен базе: новый член — единственный источник отличия."""
    ctx = _open_field_no_weapon(speed_cells_src=3)
    obs = observe(ctx)
    base = BattlecastTeacher(rounds=1).choose(ctx, obs)
    cdda = CddaRangedSupport(rounds=1, keep_distance=0.0).choose(ctx, obs)
    assert base is not None and cdda is not None
    assert base[1] == cdda[1]                              # та же клетка
    assert base[0] == pytest.approx(cdda[0])               # то же значение


def test_cdda_keep_distance_selects_farther_cell_than_base():
    ctx = _open_field_no_weapon(speed_cells_src=3)
    obs = observe(ctx)
    enemy = _enemy_cell(ctx)
    base = BattlecastTeacher(rounds=1).choose(ctx, obs)
    cdda = CddaRangedSupport(rounds=1, keep_distance=1.5).choose(ctx, obs)
    base_dist = cell_distance(base[1], enemy)
    cdda_dist = cell_distance(cdda[1], enemy)
    # база наступает (ближе к врагу), скирмишер отходит (дальше) — поведение различно
    assert base_dist < cdda_dist, (base[1], cdda[1], base_dist, cdda_dist)
