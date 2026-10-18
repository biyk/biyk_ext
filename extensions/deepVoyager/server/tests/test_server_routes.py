# tests/test_server_routes.py — HTTP-контракт эндпоинтов (через Flask test_client).
from conftest import make_scene_payload, make_wall
from server import app


def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_plan_returns_empty_actions_for_valid_payload():
    resp = client().post("/plan", json=make_scene_payload())
    assert resp.status_code == 200
    assert resp.get_json() == {"actions": []}


def test_plan_rejects_missing_body():
    resp = client().post("/plan", content_type="application/json")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_plan_rejects_invalid_payload():
    resp = client().post("/plan", json={"src": "A"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_path_endpoint_regress():
    payload = make_scene_payload()
    resp = client().post("/path", json=payload)
    assert resp.status_code == 200
    assert resp.get_json()["path"] == ["right"] * 9


def test_path_endpoint_blocked_wall_regress():
    payload = make_scene_payload(walls=[make_wall("w", 200, 0, 200, 500)])
    resp = client().post("/path", json=payload)
    assert resp.status_code == 200
    assert resp.get_json()["path"] == []


def test_plan_error_message_is_stable():
    # текст ошибки — часть контракта: JS-логирование в Foundry показывает его как есть
    resp = client().post("/plan", json={"src": "A"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Missing required fields"
