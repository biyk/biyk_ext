# tests/test_service.py — PlannerService: выбор лучшего сценария перебором (пункт 4).
import pytest

from conftest import make_npc, make_scene_payload
from planner.action import ACTION_MOVE, ACTION_TARGET, ACTION_USE
from planner.context import BattleContext
from planner.geometry import DIR_VECTORS
from planner.scoring import Scorer
from planner.service import PlannerService


def payload_with(**over):
    return {**make_scene_payload(), **over}


def test_full_approach_and_attack_with_enough_speed():
    # 50 футов = 10 шагов: direct-маршрут (9 клеток) упирается в клетку цели,
    # последний шаг убираем — 8 moves + атака с соседней клетки
    payload = payload_with(speed=50, weaponId="longsword")
    actions = PlannerService().run(payload)
    kinds = [a["action"] for a in actions]
    assert kinds[0] == ACTION_TARGET and kinds[-1] == ACTION_USE
    assert kinds[1:-1] == [ACTION_MOVE] * 8
    assert actions[0]["conf"] == {"id": "B"}
    assert actions[-1]["conf"] == {"itemId": "longsword"}
    assert {a["conf"]["direction"] for a in actions[1:-1]} == {"right"}


def test_moves_truncated_by_speed_and_no_attack_without_weapon():
    actions = PlannerService().run(payload_with())  # speed 30 → 6 шагов, weaponId нет
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
    payload = {**make_scene_payload(npcs=npcs), "weaponId": "sword"}
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
    ctx_payload = payload_with(speed=50, weaponId="longsword")
    rr = PlannerService().run_result(ctx_payload)
    assert rr.score > 0 and rr.considered >= 1
    assert [a.to_dict() for a in rr.actions] == PlannerService().run(ctx_payload)


def test_diagonal_plan_prefers_optimal_adjacent():
    # цель в клетке (4,4) по диагонали: оптимальный перебор выбирает
    # ортогонально соседнюю клетку (дистанция 1.0 < 1.414 у quin-обрезка) с атакой
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 200, 200, disposition=1)]
    payload = {**make_scene_payload(npcs=npcs), "speed": 30, "weaponId": "sword"}
    actions = PlannerService().run(payload)
    kinds = [a["action"] for a in actions]
    dirs = [a["conf"]["direction"] for a in actions if a["action"] == ACTION_MOVE]
    assert set(dirs) <= set(DIR_VECTORS)          # только легальные 8 направлений
    assert len(dirs) <= 6                         # скорость не превышена
    assert kinds[0] == ACTION_TARGET and kinds[-1] == ACTION_USE
    # очки: атака 30 + сближение 5.657 -> 1.0 (оптимум — ортогональный сосед)
    assert PlannerService().run_result(payload).score == pytest.approx(30 + 5.657 - 1.0, abs=0.02)
