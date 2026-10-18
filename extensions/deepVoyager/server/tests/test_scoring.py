# tests/test_scoring.py — очки сближения и атаки (пункт 4 todo.md).
from planner.action import Action, move_action, target_action, use_action
from planner.scoring import (
    ATTACK_POINT, DAMAGE_PENALTY, FEET_PER_CELL, MOVE_POINT_PER_CELL,
    PLAN_TIME_LIMIT_SEC, Scorer,
)
from conftest import make_npc, make_scene_payload
from planner.context import BattleContext


def test_todo_point4_constants():
    assert FEET_PER_CELL == 5
    assert MOVE_POINT_PER_CELL == 1      # 1 очко за каждые 5 футов сближения
    assert ATTACK_POINT == 30            # 30 очков за атаку
    assert PLAN_TIME_LIMIT_SEC == 5.0    # лимит расчёта — 5 секунд


def test_todo_point5_damage_penalty_constant():
    assert DAMAGE_PENALTY == -30         # штраф за получение урона


def test_empty_plan_scores_zero():
    ctx = BattleContext.from_payload(make_scene_payload())
    assert Scorer().score(ctx, []) == 0.0


def test_approach_scores_one_point_per_cell():
    # A(0,0) -> B(0,9): шесть шагов вправо сокращают прямую с 9 до 3
    ctx = BattleContext.from_payload(make_scene_payload())
    actions = [target_action("B")] + [move_action("right")] * 6
    assert Scorer().score(ctx, actions) == 6.0


def test_attack_adds_thirty():
    ctx = BattleContext.from_payload(make_scene_payload())
    actions = [target_action("B")] + [move_action("right")] * 6 + [use_action("sword")]
    assert Scorer().score(ctx, actions) == 6.0 + ATTACK_POINT


def test_moving_away_scores_negative():
    ctx = BattleContext.from_payload(make_scene_payload())
    assert Scorer().score(ctx, [move_action("left")]) == -1.0


def test_unknown_direction_ignored():
    # защита от мусора в плане: direction вне таблицы не смещает токен
    ctx = BattleContext.from_payload(make_scene_payload())
    bogus = Action("move", {"direction": "nope"})
    assert Scorer().score(ctx, [target_action("B"), bogus]) == 0.0


def test_scene_without_enemies_scores_zero():
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("N", 450, 0, disposition=0)]
    ctx = BattleContext.from_payload({**make_scene_payload(npcs=npcs), "token": None})
    assert Scorer().score(ctx, [move_action("right")] * 6 + [use_action("sword")]) == 0.0


def test_explain_reports_distance_and_attacks():
    # мини-отчёт: футы до/после сближения (кл×5) + число атак
    ctx = BattleContext.from_payload(make_scene_payload())
    actions = [target_action("B")] + [move_action("right")] * 6 + [use_action("sword")]
    text = Scorer().explain(ctx, actions)
    assert "45→15" in text               # было 45 футов (9 кл), стало 15 (3 кл)
    assert "футов" in text
    assert "+6" in text                  # очки за сближение
    assert "атак: 1" in text and "+30" in text


def test_explain_empty_without_hostiles():
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("N", 450, 0, disposition=0)]
    ctx = BattleContext.from_payload({**make_scene_payload(npcs=npcs), "token": None})
    assert Scorer().explain(ctx, [move_action("right")]) == ""
