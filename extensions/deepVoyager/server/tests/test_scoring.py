# tests/test_scoring.py — константы и базовое поведение очков (пункт 4 вырастет отсюда).
from planner.scoring import (
    ATTACK_POINT, DAMAGE_PENALTY, FEET_PER_CELL, MOVE_POINT_PER_CELL,
    PLAN_TIME_LIMIT_SEC, Scorer,
)
from planner.action import move_action
from conftest import make_scene_payload
from planner.context import BattleContext


def test_todo_point4_constants():
    assert FEET_PER_CELL == 5
    assert MOVE_POINT_PER_CELL == 1      # 1 очко за каждые 5 футов сближения
    assert ATTACK_POINT == 30            # 30 очков за атаку
    assert PLAN_TIME_LIMIT_SEC == 5.0    # лимит расчёта — 5 секунд


def test_todo_point5_damage_penalty_constant():
    assert DAMAGE_PENALTY == -30         # штраф за получение урона


def test_scorer_empty_plan_is_zero():
    ctx = BattleContext.from_payload(make_scene_payload())
    assert Scorer().score(ctx, []) == 0.0


def test_scorer_stub_returns_zero_for_any_plan():
    # До пункта 4 любой план оценивается в 0 — заглушка стабильна.
    ctx = BattleContext.from_payload(make_scene_payload())
    assert Scorer().score(ctx, [move_action("up"), move_action("right")]) == 0.0
