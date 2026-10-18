# tests/test_server_log.py — постоянный двойной лог «что пришло → что ответили».
import json

from conftest import make_npc, make_scene_payload
import server


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "LOG_JSONL", str(tmp_path / "requests.jsonl"))
    monkeypatch.setattr(server, "LOG_TEXT", str(tmp_path / "requests.log"))
    server.app.config["TESTING"] = True
    return server.app.test_client()


def test_plan_exchange_written_to_both_logs(tmp_path, monkeypatch):
    # пустая сцена (нет врагов) — ответ мгновенный, но лог обязан сохраниться
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("N", 450, 0, disposition=0)]
    payload = {**make_scene_payload(npcs=npcs), "token": None}
    resp = client(tmp_path, monkeypatch).post("/plan", json=payload)
    assert resp.status_code == 200

    record = json.loads((tmp_path / "requests.jsonl").read_text(encoding="utf-8"))
    assert record["endpoint"] == "plan"
    assert record["request"]["data"]["npcs"][0]["id"] == "A"   # полный приход
    assert record["response"] == {"actions": []}               # полный ответ
    assert "ts" in record

    text = (tmp_path / "requests.log").read_text(encoding="utf-8")
    assert "POST /plan" in text and "ПРИШЛО" in text and "ОТВЕТ" in text


def test_path_exchange_written(tmp_path, monkeypatch):
    resp = client(tmp_path, monkeypatch).post("/path", json=make_scene_payload())
    assert resp.status_code == 200
    record = json.loads((tmp_path / "requests.jsonl").read_text(encoding="utf-8"))
    assert record["endpoint"] == "path"
    assert record["response"] == {"path": ["right"] * 9}


def test_log_append_keeps_history(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("N", 450, 0, disposition=0)]
    payload = {**make_scene_payload(npcs=npcs), "token": None}
    c.post("/plan", json=payload)
    c.post("/plan", json=payload)
    lines = (tmp_path / "requests.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2                            # каждая проверка — новая строка
