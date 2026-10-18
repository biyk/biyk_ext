# tests/test_scoring.py — очки сближения и атаки (пункт 4 todo.md).
from planner.action import Action, move_action, target_action, use_action
from planner.scoring import (
    ATTACK_DOUBT_POINT, ATTACK_POINT, DAMAGE_PENALTY, FEET_PER_CELL,
    MOVE_POINT_PER_CELL, PLAN_TIME_LIMIT_SEC, Scorer,
)
from conftest import make_npc, make_scene_payload, make_weapon
from planner.context import BattleContext


def test_todo_point4_constants():
    assert FEET_PER_CELL == 5
    assert MOVE_POINT_PER_CELL == 1      # 1 очко за каждые 5 футов сближения
    assert ATTACK_POINT == 30            # 30 очков за уверенную атаку
    assert ATTACK_DOUBT_POINT == 15      # 15 очков за сомнительную (дальняя дистанция)
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


def test_doubt_attack_scores_fifteen():
    # лук 30/120 футов, цель в 8 клетках (40 футов) — вне уверенной зоны
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 400, 0, disposition=1)]
    ctx = BattleContext.from_payload(
        make_scene_payload(npcs=npcs, weapons=[make_weapon("bow", sure_ft=30, doubt_ft=120)]))
    actions = [target_action("B"), use_action("bow")]
    assert Scorer().score(ctx, actions) == float(ATTACK_DOUBT_POINT)
    assert "сомнительная" in Scorer().explain(ctx, actions) and "+15" in Scorer().explain(ctx, actions)


def test_sure_attack_in_close_range_scores_thirty():
    # тот же лук, но цель в 4 клетках (20 футов) — уверенная зона (30 футов)
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 200, 0, disposition=1)]
    ctx = BattleContext.from_payload(
        make_scene_payload(npcs=npcs, weapons=[make_weapon("bow", sure_ft=30, doubt_ft=120)]))
    actions = [target_action("B"), use_action("bow")]
    assert Scorer().score(ctx, actions) == float(ATTACK_POINT)
    assert "уверенная" in Scorer().explain(ctx, actions)


def test_ranged_attack_at_point_blank_scores_doubt():
    # лук 30/120, но враг вплотную (5 футов) — выстрел в упор, только сомнительно
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 50, 0, disposition=1)]
    ctx = BattleContext.from_payload(
        make_scene_payload(npcs=npcs, weapons=[make_weapon("bow", sure_ft=30, doubt_ft=120)]))
    actions = [target_action("B"), use_action("bow")]
    assert Scorer().score(ctx, actions) == float(ATTACK_DOUBT_POINT)
    assert "сомнительная" in Scorer().explain(ctx, actions)


def test_thrown_attack_at_point_blank_scores_sure():
    # метательный нож 20/60 вплотную — бросок без помехи, уверенная атака (30)
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 50, 0, disposition=1)]
    ctx = BattleContext.from_payload(make_scene_payload(
        npcs=npcs, weapons=[make_weapon("knife", sure_ft=20, doubt_ft=60,
                                        ranged=True, properties=["thr"])]))
    actions = [target_action("B"), use_action("knife")]
    assert Scorer().score(ctx, actions) == float(ATTACK_POINT)
    assert "уверенная" in Scorer().explain(ctx, actions)


def test_attack_out_of_every_range_scores_nothing():
    # ближний бой против цели в 8 клетках: атака не засчитывается совсем
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 400, 0, disposition=1)]
    ctx = BattleContext.from_payload(make_scene_payload(npcs=npcs, weapons=[make_weapon("club")]))
    actions = [target_action("B"), move_action("left"), use_action("club")]
    assert Scorer().score(ctx, actions) == -1.0


def test_explain_empty_without_hostiles():
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("N", 450, 0, disposition=0)]
    ctx = BattleContext.from_payload({**make_scene_payload(npcs=npcs), "token": None})
    assert Scorer().explain(ctx, [move_action("right")]) == ""


def test_breakdown_approach_counts_to_attacked_target():
    # Вплотную стоит NEAR, цель выстрела — FAR в 6 клетках: очки за сближение
    # считаются до того, на кого указывает target-действие, а не до ближайшего.
    npcs = [make_npc("A", 0, 0, disposition=-1),
            make_npc("NEAR", 50, 0, disposition=1),
            make_npc("FAR", 300, 0, disposition=1)]
    ctx = BattleContext.from_payload(make_scene_payload(
        npcs=npcs, token="NEAR",
        weapons=[make_weapon("bow", sure_ft=30, doubt_ft=120, ranged=True)]))
    b = Scorer().breakdown(ctx, [target_action("FAR"), use_action("bow")])
    assert b["ref_kind"] == "target" and b["ref_id"] == "FAR"
    assert (b["before"], b["after"]) == (6.0, 6.0)
    assert b["approach"] == 0.0
    assert b["sure"] == 1


def test_breakdown_without_attack_uses_nearest_enemy():
    # План без атаки (только движение) — прежнее измерение до ближайшего врага.
    npcs = [make_npc("A", 0, 0, disposition=-1),
            make_npc("NEAR", 300, 0, disposition=1),
            make_npc("FAR", 400, 0, disposition=1)]
    ctx = BattleContext.from_payload(make_scene_payload(npcs=npcs))
    b = Scorer().breakdown(ctx, [target_action("FAR")] + [move_action("right")] * 2)
    assert b["ref_kind"] == "nearest" and b["ref_id"] == "NEAR"
    assert (b["before"], b["after"]) == (6.0, 4.0)
    assert b["approach"] == 2.0


def test_explain_mentions_weapon_and_target_name():
    # Мини-отчёт называет оружие и цель атаки — иначе «1 уверенная (+30)»
    # невозможно объяснить, не глядя в запрос.
    npcs = [make_npc("A", 0, 0, disposition=-1),
            make_npc("B", 200, 0, disposition=1, name="Стражник (1)")]
    ctx = BattleContext.from_payload(make_scene_payload(
        npcs=npcs, weapons=[make_weapon("knife", name="Кинжал", sure_ft=20,
                                        properties=["thr"])]))
    text = Scorer().explain(ctx, [target_action("B"), use_action("knife")])
    assert "Кинжал" in text and "Стражник (1)" in text
    assert "→ «Стражник (1)» B" in text      # имена повторяются, поэтому нужен id
    assert "к цели" in text

