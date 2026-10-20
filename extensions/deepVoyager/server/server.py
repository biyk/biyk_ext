# extensions/deepVoyager/server/server.py
# Flask-сервер для deepVoyager: /ask (LLM-действия) и /path (расчёт пути).
# Портирован из прототипа C:\Users\b5\Desktop\DeepWeb (шаг 2 плана todo.md).
import json
import sys
import os
import io
import uuid
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

# UTF-8 консоль в Windows; при захвате вывода (pytest) .buffer может отсутствовать
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if getattr(_stream, "buffer", None) is not None and getattr(_stream, "encoding", "").lower() != "utf-8":
        setattr(sys, _stream_name, io.TextIOWrapper(_stream.buffer, encoding="utf-8"))

from dotenv import load_dotenv
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

from flask import Flask, request, jsonify
from flask_cors import CORS
from src.deepseek import ask
from libs.quin import find_path_from_data
from planner.service import PlannerService
from planner.armament import parse_properties
from planner.points import tuning
from arent import capture as arent_capture   # сбор живых состояний для обучения (arent/capture.py)

app = Flask(__name__)
CORS(app)

app.config['JSON_AS_ASCII'] = False

# DeepSeek временно выключен: /ask не запускает браузер/чат, пока DEEPSEEK_ENABLED!=true.
DEEPSEEK_ENABLED = os.getenv("DEEPSEEK_ENABLED", "false").strip().lower() == "true"


def _log(tag, msg):
    """Строка в консоль сервера: видно каждый запрос и его итог."""
    print(f"[{tag}] {msg}", flush=True)


def _event_id():
    """Короткий id обмена: по нему строки консоли связываются с записью в logs/."""
    return uuid.uuid4().hex[:8]


# Постоянный журнал запросов/ответов: пути читаются в момент записи (тесты
# подменяют модульные переменные). Каталог — server/logs или PLAN_LOG_DIR.
LOG_DIR = os.getenv("PLAN_LOG_DIR") or os.path.join(SCRIPT_DIR, "logs")
LOG_JSONL = os.path.join(LOG_DIR, "requests.jsonl")   # машиночитаемый, по записи в строку
LOG_TEXT = os.path.join(LOG_DIR, "requests.log")      # читаемый блоками


def _log_exchange(endpoint, request_obj, response_obj, summary="", event=""):
    """Полное «что пришло -> что ответили» в оба файла; ошибки не ломают запрос."""
    ts = datetime.now().isoformat(timespec="seconds")
    try:
        os.makedirs(os.path.dirname(LOG_JSONL), exist_ok=True)
        with open(LOG_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": ts, "event": event, "endpoint": endpoint,
                                "request": request_obj,
                                "response": response_obj, "summary": summary},
                               ensure_ascii=False) + "\n")
        with open(LOG_TEXT, "a", encoding="utf-8") as f:
            f.write(f"=== [{ts}] POST /{endpoint} #{event} ===\n"
                    f"ПРИШЛО: {json.dumps(request_obj, ensure_ascii=False)}\n"
                    f"ОТВЕТ: {json.dumps(response_obj, ensure_ascii=False)}\n"
                    f"ИТОГ: {summary}\n\n")
    except OSError as e:
        _log("log", f"не удалось записать в файл: {e}")


def describe_actions(actions):
    """Список действий для лога: каждый move подписан направлением (move→right)."""
    parts = []
    for a in actions:
        if a["action"] == "move":
            parts.append(f"move→{a['conf'].get('direction', '?')}")
        else:
            parts.append(a["action"])
    return "[" + ", ".join(parts) + "]"


def describe_weapons(payload):
    """Список оружия из запроса для лога: «Праща id[урон, sure/doubtфт, метка]»."""
    return ", ".join(weapon_description(w) for w in payload.get("weapons") or []) or "без оружия"


def weapon_description(entry):
    """Одна запись: имя (если прислано) + id + урон, зоны попадания и метка."""
    wid, name = str(entry.get("id")), str(entry.get("name") or "")
    label = f"{name} {wid}" if name and name != wid else wid
    return (f"{label}[{entry.get('damage') or '-'}, {entry.get('sureFt')}/"
            f"{entry.get('doubtFt')}фт{weapon_marks(entry)}]")


def weapon_marks(entry):
    """Метки для консоли: метат (в упор уверенно) либо дальноб (в упор с помехой)."""
    if tuning().thrown_property in parse_properties(entry.get("properties")):
        return ", метат"
    return ", дальноб" if is_ranged_entry(entry) else ""


def is_ranged_entry(entry):
    """Дальнобойная ли запись: явный флаг, иначе — по длинной дистанции."""
    if "ranged" in entry:
        return bool(entry["ranged"])
    return _feet(entry.get("doubtFt")) > _feet(entry.get("sureFt"))


def _feet(value):
    """Футы из payload в число; мусор (строка/None) — нули, лог не должен падать."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


@app.route("/ask", methods=["POST"])
def ask_endpoint():
    event = _event_id()
    if not DEEPSEEK_ENABLED:
        _log("ask", f"#{event} ОТКЛОНЁН: DeepSeek временно отключён (DEEPSEEK_ENABLED=false в .env)")
        return jsonify({"error": "DeepSeek disabled (set DEEPSEEK_ENABLED=true to enable)"}), 503
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "Missing 'text' field"}), 400
    try:
        _log("ask", f"#{event} запрос LLM, {len(data['text'])} симв.")
        response = ask(data["text"])
        _log("ask", f"#{event} ответ: {str(response)[:120]}...")
        _log_exchange("ask", data, {"response": str(response)}, event=event)
        return jsonify({"response": response}), 200, {"Content-Type": "application/json; charset=utf-8"}
    except Exception as e:
        _log("ask", f"#{event} ошибка: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/path", methods=["POST"])
def path_endpoint():
    event = _event_id()
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
    try:
        _log("path", f"#{event} src={data.get('src')} token={data.get('token')} "
                     f"mode={data.get('mode')}")
        path = find_path_from_data(data)
        _log("path", f"#{event} итог: {path}")
        _log_exchange("path", data, {"path": path}, str(path), event=event)
        return jsonify({"path": path}), 200, {"Content-Type": "application/json; charset=utf-8"}
    except ValueError as e:
        _log("path", f"#{event} ошибка входа: {e}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        _log("path", f"#{event} ошибка: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/plan", methods=["POST"])
def plan_endpoint():
    # Собственный расчёт хода NPC вместо ответа LLM (пункт 3 todo.md).
    # Контракт совпадает с /ask: {"actions": [...]}.
    event = _event_id()
    data = request.get_json(silent=True)
    if not data:
        _log("plan", f"#{event} ОШИБКА: пустое JSON-тело запроса")
        return jsonify({"error": "Missing JSON body"}), 400
    _log("plan", f"#{event} src={data.get('src')} token={data.get('token')} "
                 f"speed={data.get('speed')} оружие: {describe_weapons(data)}")
    try:
        result = PlannerService().run_result(data)
        actions = result.action_dicts
        summary = (f"итог: {len(actions)} действий -> {describe_actions(actions)} | "
                   f"очков: {result.score:g} | вариантов просчитано: {result.considered}"
                   + (f" | {result.details}" if result.details else ""))
        _log("plan", f"#{event} {summary}")
        _log_exchange("plan", data, {"actions": actions}, summary, event=event)
        arent_capture.capture(data, {"actions": actions}, event=event)
        return jsonify({"actions": actions}), 200, {"Content-Type": "application/json; charset=utf-8"}
    except ValueError as e:
        _log("plan", f"#{event} ошибка входа: {e}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        _log("plan", f"#{event} ошибка: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("SERVER_PORT", "9999"))
    _log("server", f"старт на порту {port}; DeepSeek: "
                   + ("ВКЛЮЧЁН" if DEEPSEEK_ENABLED else "ОТКЛЮЧЁН (DEEPSEEK_ENABLED=false)"))
    app.run(host="0.0.0.0", port=port)
