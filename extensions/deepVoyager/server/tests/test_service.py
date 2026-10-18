# tests/test_service.py — PlannerService: выбор лучшего сценария перебором (пункт 4).
import pytest

from conftest import make_npc, make_scene_payload, make_weapon
from planner.action import ACTION_MOVE, ACTION_TARGET, ACTION_USE
from planner.context import BattleContext
from planner.geometry import DIR_VECTORS
from planner.scoring import Scorer
from planner.service import PlannerService


def payload_with(**over):
    return {**make_scene_payload(), **over}


def test_full_approach_and_attack_with_enough_speed():
    # 50 футов = 10 шагов: до B (9 клеток) не дойти — встаём в соседнюю (0,8),
    # оттуда ближний бой уверенно достает: 8 moves + атака
    payload = {**make_scene_payload(weapons=[make_weapon("longsword")]), "speed": 50}
    actions = PlannerService().run(payload)
    kinds = [a["action"] for a in actions]
    assert kinds[0] == ACTION_TARGET and kinds[-1] == ACTION_USE
    assert kinds[1:-1] == [ACTION_MOVE] * 8
    assert actions[0]["conf"] == {"id": "B"}
    assert actions[-1]["conf"] == {"itemId": "longsword"}
    assert {a["conf"]["direction"] for a in actions[1:-1]} == {"right"}


def test_moves_truncated_by_speed_and_no_attack_without_weapon():
    actions = PlannerService().run(payload_with())  # speed 30 → 6 шагов, weapons пустые
    moves = [a for a in actions if a["action"] == ACTION_MOVE]
    assert len(moves) == 6
    assert not any(a["action"] == ACTION_USE for a in actions)


def test_no_hostiles_empty_plan():
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("N", 450, 0, disposition=0)]
    assert PlannerService().run({**make_scene_payload(npcs=npcs), "token": None}) == []


def test_deadline_keeps_best_of_reviewed_candidates():
    # Скорость 30 (6 шагов): до B (9 клеток) не дойти — только сближение на 6 очков,
    # а M (2 клетки) достигается с атакой за 32. Нулевой лимит — фиксируется первый
    # рассмотренный кандидат (B); полный лимит выбирается лучший (M+атака).
    npcs = [
        make_npc("A", 0, 0, disposition=-1),
        make_npc("B", 450, 0, disposition=1),
        make_npc("M", 100, 0, disposition=1),
    ]
    payload = {**make_scene_payload(npcs=npcs, weapons=[make_weapon("sword")])}
    ctx = BattleContext.from_payload(payload)

    rushed = PlannerService(time_limit_sec=0.0).plan(ctx)
    # рассмотрен ровно один кандидат (B) — M в торопливом плане недостижим
    assert rushed == [] or rushed[0].conf["id"] == "B"

    full = PlannerService().plan(ctx)
    assert full[0].conf["id"] == "M"
    assert full[-1].action == ACTION_USE
    assert full != rushed


def test_scorer_injectable_and_used():
    calls = []

    class RecordingScorer(Scorer):
        def score(self, context, actions):
            calls.append(len(actions))
            return 7.0

    service = PlannerService(scorer=RecordingScorer())
    assert service.scorer.__class__.__name__ == "RecordingScorer"
    plan = service.plan(BattleContext.from_payload(payload_with()))
    assert plan and calls  # каждый кандидат оценён внедрённым скорером


def test_invalid_payload_raises_value_error():
    with pytest.raises(ValueError):
        PlannerService().run({"src": "A"})


def test_result_items_are_plain_dicts():
    # намеренно: результат уходит в jsonify без кастомных кодировщиков
    out = PlannerService().run(payload_with())
    assert isinstance(out, list) and all(isinstance(x, dict) for x in out)


def test_plan_result_reports_score_and_considered_count():
    # PlanResult несёт диагностику для консоли: заработанные очки и число
    # просмотренных кандидатов (перебор цель × direct/los).
    ctx = BattleContext.from_payload(payload_with())
    result = PlannerService().plan_result(ctx)
    assert result.score > 0            # сближение на 6 клеток = 6.0
    assert result.considered >= 1      # хотя бы один сценарий просчитан
    assert "сближение" in result.details  # мини-отчёт «за что очки»
    assert result.actions == PlannerService().plan(ctx)  # план — тот же, что у plan()


def test_plan_result_empty_scene_zero_score_zero_candidates():
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("N", 450, 0, disposition=0)]
    ctx = BattleContext.from_payload({**make_scene_payload(npcs=npcs), "token": None})
    result = PlannerService().plan_result(ctx)
    assert result.actions == []
    assert result.score == 0.0
    assert result.considered == 0
    assert result.details == ""


def test_run_result_is_shorthand_of_plan_result():
    ctx_payload = {**make_scene_payload(weapons=[make_weapon("longsword")]), "speed": 50}
    rr = PlannerService().run_result(ctx_payload)
    assert rr.score > 0 and rr.considered >= 1
    assert [a.to_dict() for a in rr.actions] == PlannerService().run(ctx_payload)


def test_diagonal_plan_prefers_optimal_adjacent():
    # цель в клетке (4,4) по диагонали: оптимальный перебор выбирает
    # ортогонально соседнюю клетку (дистанция 1.0 < 1.414 у quin-обрезка) с атакой
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 200, 200, disposition=1)]
    payload = {**make_scene_payload(npcs=npcs, weapons=[make_weapon("sword")]), "speed": 30}
    actions = PlannerService().run(payload)
    kinds = [a["action"] for a in actions]
    dirs = [a["conf"]["direction"] for a in actions if a["action"] == ACTION_MOVE]
    assert set(dirs) <= set(DIR_VECTORS)          # только легальные 8 направлений
    assert len(dirs) <= 6                         # скорость не превышена
    assert kinds[0] == ACTION_TARGET and kinds[-1] == ACTION_USE
    # очки: атака 30 + сближение 5.657 -> 1.0 (оптимум — ортогональный сосед)
    assert PlannerService().run_result(payload).score == pytest.approx(30 + 5.657 - 1.0, abs=0.02)


def test_chooses_ranged_weapon_when_melee_cannot_reach():
    # враг в 9 клетках, ход 6 клеток: сблизившись на 6, ближним боем не достать,
    # зато достает лук (30 футов = 6 клеток уверенно) — выбор оружия делает план
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 450, 0, disposition=1)]
    payload = {**make_scene_payload(npcs=npcs,
                                    weapons=[make_weapon("club"),
                                             make_weapon("bow", name="лук", sure_ft=30,
                                                        doubt_ft=120)]),
               "speed": 30}
    actions = PlannerService().run(payload)
    assert actions[-1] == {"action": ACTION_USE, "conf": {"itemId": "bow"}}
    assert PlannerService().run_result(payload).score == pytest.approx(6.0 + 30.0)
    # без лука атаковать нечем — остаётся только сближение
    melee_only = {**make_scene_payload(npcs=npcs, weapons=[make_weapon("club")]), "speed": 30}
    solo = PlannerService().run(melee_only)
    assert not any(a["action"] == ACTION_USE for a in solo)


def test_doubt_attack_is_preferred_over_bare_approach():
    # сомнительная (15) лучше, чем не стрелять: цель в 9 клетках, уверенная зона
    # только в 1 клетке — шестой ход даёт сближение 6 + сомнительную атаку 15
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 450, 0, disposition=1)]
    payload = {**make_scene_payload(npcs=npcs,
                                    weapons=[make_weapon("hunter", sure_ft=5, doubt_ft=60)]),
               "speed": 30}
    result = PlannerService().run_result(payload)
    assert result.actions[-1].conf == {"itemId": "hunter"}
    assert result.score == pytest.approx(6.0 + 15.0)
    assert "сомнительная" in result.details


def test_ranged_attacker_stops_at_sure_range_instead_of_point_blank():
    # лук 30/120, враг в 7 клетках (35 футов), ход 6 клеток: шестой шаг ставит вплотную
    # (сомнительная 15 + 6 сближения = 21), поэтому перебор встаёт в 2 клетках: 5 + 30
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 350, 0, disposition=1)]
    payload = {**make_scene_payload(npcs=npcs,
                                    weapons=[make_weapon("bow", sure_ft=30, doubt_ft=120)]),
               "speed": 30}
    actions = PlannerService().run(payload)
    dirs = [a["conf"]["direction"] for a in actions if a["action"] == ACTION_MOVE]
    assert dirs == ["right"] * 5                  # последний шаг в упор не делается
    assert actions[-1] == {"action": ACTION_USE, "conf": {"itemId": "bow"}}
    result = PlannerService().run_result(payload)
    assert result.score == pytest.approx(5.0 + 30.0)
    assert "уверенная" in result.details


def test_thrown_attacker_closes_to_point_blank_for_sure_attack():
    # тот же лук 30/120, но метательный (свойство thr): в упор бросок уверенный,
    # поэтому шестой шаг выгоден — 6 сближения + 30, а не 5 + 30 с позиции в 2 клетках
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 350, 0, disposition=1)]
    payload = {**make_scene_payload(npcs=npcs,
                                    weapons=[make_weapon("knife", sure_ft=30, doubt_ft=120,
                                                         ranged=True, properties=["thr"])]),
               "speed": 30}
    actions = PlannerService().run(payload)
    dirs = [a["conf"]["direction"] for a in actions if a["action"] == ACTION_MOVE]
    assert dirs == ["right"] * 6                  # вплотную — без помехи
    assert actions[-1] == {"action": ACTION_USE, "conf": {"itemId": "knife"}}
    assert PlannerService().run_result(payload).score == pytest.approx(6.0 + 30.0)


def test_closing_attack_outranks_static_max_range_shot():
    # Копия залогированной ситуации #80ac71c9: один враг вплотную, второй в 6 клетках,
    # праща 30/120 + метательный кинжал 5/5. Подход к атакуемой цели стоит очков,
    # поэтому «пройти 5 клеток и ударить кинжалом» (5 + 30) выгоднее,
    # чем «стоять и стрелять на пределе уверенной зоны» (30).
    npcs = [make_npc("A", 0, 0, disposition=-1),
            make_npc("NEAR", 50, 0, disposition=1, name="Стражник (1)"),
            make_npc("FAR", 300, 0, disposition=1, name="Стражник (2)")]
    payload = {**make_scene_payload(npcs=npcs, token="NEAR",
                                    weapons=[make_weapon("sling", name="Праща", sure_ft=30,
                                                         doubt_ft=120, ranged=True, properties=["amm"]),
                                             make_weapon("knife", name="Кинжал", sure_ft=5,
                                                        doubt_ft=5, ranged=False, properties=["thr"])]),
               "speed": 30}
    result = PlannerService(time_limit_sec=1.0).run_result(payload)
    dirs = [a for a in result.action_dicts if a["action"] == ACTION_MOVE]
    used = [a for a in result.action_dicts if a["action"] == ACTION_USE]
    assert len(dirs) == 5 and used[0]["conf"]["itemId"] == "knife"
    assert result.score == pytest.approx(5.0 + 30.0)
    assert "Праща" not in result.details
    assert "Кинжал" in result.details and "Стражник (2)" in result.details

