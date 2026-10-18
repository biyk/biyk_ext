# tests/test_service.py — контракт PlannerService (пункт 3: пустой массив).
import pytest

from conftest import make_scene_payload
from planner.context import BattleContext
from planner.scoring import Scorer
from planner.service import PlannerService


def test_plan_is_empty_array_for_now(scene_payload):
    # Ключевое поведение шага 3: сервер отвечает пустым планом, контракт зафиксирован.
    assert PlannerService().run(scene_payload) == []


def test_plan_method_returns_action_list_type(scene_payload):
    ctx = BattleContext.from_payload(scene_payload)
    assert PlannerService().plan(ctx) == []


def test_invalid_payload_raises_value_error():
    with pytest.raises(ValueError):
        PlannerService().run({"src": "A"})


def test_scorer_injectable():
    scorer = Scorer()
    service = PlannerService(scorer=scorer)
    assert service.scorer is scorer


def test_result_items_are_plain_dicts(scene_payload):
    # намеренно: результат уходит в jsonify без кастомных кодировщиков
    out = PlannerService().run(scene_payload)
    assert isinstance(out, list) and all(isinstance(x, dict) for x in out)
