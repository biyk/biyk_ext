# extensions/deepVoyager/server/server.py
# Flask-сервер для deepVoyager: /ask (LLM-действия) и /path (расчёт пути).
# Портирован из прототипа C:\Users\b5\Desktop\DeepWeb (шаг 2 плана todo.md).
import sys
import os
import io

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

app = Flask(__name__)
CORS(app)

app.config['JSON_AS_ASCII'] = False


@app.route("/ask", methods=["POST"])
def ask_endpoint():
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "Missing 'text' field"}), 400
    try:
        response = ask(data["text"])
        return jsonify({"response": response}), 200, {"Content-Type": "application/json; charset=utf-8"}
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/path", methods=["POST"])
def path_endpoint():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
    try:
        path = find_path_from_data(data)
        return jsonify({"path": path}), 200, {"Content-Type": "application/json; charset=utf-8"}
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/plan", methods=["POST"])
def plan_endpoint():
    # Собственный расчёт хода NPC вместо ответа LLM (пункт 3 todo.md).
    # Пока возвращает пустой массив; контракт совпадает с /ask: {"actions": [...]}.
    data = request.get_json(silent=True)
    try:
        actions = PlannerService().run(data)
        return jsonify({"actions": actions}), 200, {"Content-Type": "application/json; charset=utf-8"}
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("SERVER_PORT", "9999"))
    app.run(host="0.0.0.0", port=port)
