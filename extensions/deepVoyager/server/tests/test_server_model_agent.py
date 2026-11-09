# tests/test_server_model_agent.py — /plan умеет ходить двумя агентами.
#
# planner (по умолчанию) — эвристический учитель, ничего не меняем;
# model — нейронная политика arent/play.py, чтобы кнопка deepvoyager-play-btn
# в Foundry реально проверяла чекпойнет, а не планировщика.
import pytest

import server
from conftest import make_scene_payload


def client():
    server.app.config["TESTING"] = True
    return server.app.test_client()


@pytest.fixture
def captured(monkeypatch):
    """Собираем вызовы arent.capture.capture, чтобы тесты не плодили живые снимки."""
    rows = []
    monkeypatch.setattr(server.arent_capture, "capture",
                        lambda payload, plan=None, event="": rows.append(plan) or "x")
    return rows


@pytest.fixture
def no_planner(monkeypatch):
    """Планировщик должен падать: тихий откат на учителя выдал бы «тест модели» вместо него."""
    def boom(*_a, **_kw):
        raise AssertionError("PlannerService вызван там, где должна ходить модель")
    monkeypatch.setattr(server, "PlannerService", boom)
    return boom


def _fake_act(monkeypatch, actions):
    seen = {}

    def act(model, payload):
        seen["payload"] = payload
        return {"actions": actions, "value": 0.42, "me": "A1",
                "names": {"cell": "right->right", "target": "B", "weapon": "Длинный лук"}}

    monkeypatch.setattr("arent.play.act", act)
    monkeypatch.setattr(server, "_model_of", lambda: ("runs/s41es/model.json", object()))
    return seen


def test_plan_agent_default_is_planner():
    assert server.PLAN_AGENT == "planner"


def test_plan_model_agent_returns_foundry_contract(monkeypatch, captured, no_planner):
    seen = _fake_act(monkeypatch, [{"action": "target", "conf": {"id": "B"}}])
    monkeypatch.setattr(server, "PLAN_AGENT", "model")
    resp = client().post("/plan", json=make_scene_payload())
    assert resp.status_code == 200
    assert resp.get_json() == {"actions": [{"action": "target", "conf": {"id": "B"}}]}
    assert seen["payload"]["src"] == "A"                      # модели отдаётся ровно тот же payload
    assert seen["payload"]["data"]["scene"]["gridSize"] == 50
    assert captured and captured[0]["agent"] == "model"       # метка: это ответ политики, не учителя


def test_plan_model_agent_error_does_not_fall_back(monkeypatch, captured, no_planner):
    def boom():
        raise RuntimeError("Чекпойнета модели нет: PLAN_MODEL='нет-такой'")

    monkeypatch.setattr(server, "PLAN_AGENT", "model")
    monkeypatch.setattr(server, "_model_of", boom)
    resp = client().post("/plan", json=make_scene_payload())
    assert resp.status_code == 500
    assert "Чекпойнета модели нет" in resp.get_json()["error"]
    assert captured == []                                     # сломанный ход не записывается как пример


def test_plan_planner_agent_tags_capture_as_planner(monkeypatch, captured):
    resp = client().post("/plan", json=make_scene_payload())
    assert resp.status_code == 200
    assert resp.get_json()["actions"][0] == {"action": "target", "conf": {"id": "B"}}
    assert captured and captured[0]["agent"] == "planner"
