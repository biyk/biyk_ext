# tests/test_server_log.py — постоянный двойной лог «что пришло → что ответили».
import json
import re

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


def test_log_lines_share_event_id(tmp_path, monkeypatch, capsys):
    # id события связывает строки консоли и обе записи журнала в один обмен
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("N", 450, 0, disposition=0)]
    payload = {**make_scene_payload(npcs=npcs), "token": None}
    client(tmp_path, monkeypatch).post("/plan", json=payload)

    ids = re.findall(r"#([0-9a-f]{8})", capsys.readouterr().out)
    assert len(ids) >= 2 and set(ids) == {ids[0]}      # запрос и итог — один и тот же id

    record = json.loads((tmp_path / "requests.jsonl").read_text(encoding="utf-8"))
    assert record["event"] == ids[0]
    text = (tmp_path / "requests.log").read_text(encoding="utf-8")
    assert f"POST /plan #{ids[0]}" in text


def test_path_log_lines_share_event_id(tmp_path, monkeypatch, capsys):
    client(tmp_path, monkeypatch).post("/path", json=make_scene_payload())
    ids = re.findall(r"#([0-9a-f]{8})", capsys.readouterr().out)
    assert len(ids) >= 2 and set(ids) == {ids[0]}
    record = json.loads((tmp_path / "requests.jsonl").read_text(encoding="utf-8"))
    assert record["event"] == ids[0]


def test_describe_weapons_marks_ranged_and_thrown():
    # в консоли видно имя, id, дальнобойность и метательность: без имени
    # вопрос «почему он атаковал пращей?» на одну строку лога не закрыть
    text = server.describe_weapons({"weapons": [
        {"id": "bow", "name": "Длинный лук", "damage": "1d4", "sureFt": 30, "doubtFt": 120,
         "ranged": True},
        {"id": "knife", "name": "Кинжал", "damage": "1d4", "sureFt": 20, "doubtFt": 60,
         "ranged": True, "properties": ["thr"]},
        {"id": "club", "name": "Дубина", "damage": "1d4", "sureFt": 5, "doubtFt": 5},
    ]})
    assert "Длинный лук bow[1d4, 30/120фт, дальноб]" in text
    assert "Кинжал knife[1d4, 20/60фт, метат]" in text     # метат, а не дальноб
    assert text.endswith("Дубина club[1d4, 5/5фт]")


def test_describe_weapons_without_name_keeps_bare_id():
    # старый клиент без поля name: строка не должна начинаться с пробела
    text = server.describe_weapons({"weapons": [
        {"id": "bow", "damage": "1d4", "sureFt": 30, "doubtFt": 120, "ranged": True}]})
    assert text == "bow[1d4, 30/120фт, дальноб]"
