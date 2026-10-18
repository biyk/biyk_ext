# tests/test_server_routes.py — HTTP-контракт эндпоинтов (через Flask test_client).
from conftest import make_npc, make_scene_payload, make_wall
from server import app, describe_actions


def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_plan_returns_actions_for_hostile_scene():
    # враждебная сцена по умолчанию: 6 шагов вправо (speed 30) к цели B
    resp = client().post("/plan", json=make_scene_payload())
    assert resp.status_code == 200
    actions = resp.get_json()["actions"]
    assert actions[0] == {"action": "target", "conf": {"id": "B"}}
    assert [a["conf"]["direction"] for a in actions if a["action"] == "move"] == ["right"] * 6


def test_plan_returns_empty_actions_when_no_hostiles():
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("N", 450, 0, disposition=0)]
    resp = client().post("/plan", json={**make_scene_payload(npcs=npcs), "token": None})
    assert resp.status_code == 200
    assert resp.get_json() == {"actions": []}


def test_plan_unreachable_target_still_approaches():
    # цель отрезана глухой стеной: атаковать нечем, но лучший по очкам ход —
    # сближаться настолько, насколько пускают стены (новая философия перебора)
    payload = make_scene_payload(walls=[make_wall("w", 200, 0, 200, 500)])
    resp = client().post("/plan", json=payload)
    assert resp.status_code == 200
    actions = resp.get_json()["actions"]
    assert actions[0]["action"] == "target"
    assert all(a["action"] == "move" for a in actions[1:])  # без атаки — цель недостижима
    assert len(actions[1:]) > 0                              # сближение выполняется


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


def test_describe_actions_shows_move_direction():
    # в лог-строке каждый move подписан направлением, остальные действия как есть
    actions = [
        {"action": "target", "conf": {"id": "B"}},
        {"action": "move", "conf": {"direction": "downright"}},
        {"action": "move", "conf": {"direction": "right"}},
        {"action": "use", "conf": {"itemId": "wk"}},
    ]
    assert describe_actions(actions) == "[target, move→downright, move→right, use]"


def test_describe_actions_unknown_direction_marked():
    assert describe_actions([{"action": "move", "conf": {}}]) == "[move→?]"
