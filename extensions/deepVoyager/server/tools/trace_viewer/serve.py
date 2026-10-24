# tools/trace_viewer/serve.py — статикa вьюера + эндпоинт /refresh для кнопки 🔄.
#
# Чем это отличается от `python -m http.server 8317`: то же самое плюс GET /refresh,
# который перегоняет parse_traces.py по свежим дампам .ray/traces_all_*.json и отдаёт
# JSON {ok, out}. Кнопка 🔄 во viewer.html дергает /refresh и перезагружает страницу.
#
# Запуск (из любой папки, порт по умолчанию 8317):
#   C:\Users\b5\AppData\Local\FoundryVTT\Data\modules\biyk_ext\extensions\deepVoyager\server\arent\.venv\Scripts\python.exe ^
#     C:\Users\b5\AppData\Local\FoundryVTT\Data\modules\biyk_ext\extensions\deepVoyager\server\tools\trace_viewer\serve.py
#   serve.py [порт]            # свой порт
#
# parse_traces.py — чистый stdlib, поэтому какой python запускает сервер, тот и парсит.
import http.server
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8317
PARSE = os.path.join(HERE, "parse_traces.py")
_LOCK = threading.Lock()          # параллельные клики 🔄 не должны гонять парсер дважды
_PLOCK = threading.Lock()         # запись флагов enabled в points.json не должна перезаписать саму себя
POINTS = os.path.normpath(os.path.join(HERE, "..", "..", "points.json"))
SERVER = os.path.normpath(os.path.join(HERE, "..", ".."))
PIPELINE = os.path.join(SERVER, ".ray", "run_pipeline.py")
STATUS = os.path.join(SERVER, ".ray", "retrain_status.json")
RUNLOG = os.path.join(SERVER, ".ray", "retrain_web.log")
DEFAULT_RUN = "s3im4_gpu"
_NEW_PROCESS_GROUP = 0x00000200     # CREATE_NEW_PROCESS_GROUP: Ctrl+C в консоли сервера не рвёт прогон
_PIPELINE = {"proc": None}          # один фоновый прогон на процесс serve.py


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/refresh":
            self._refresh()
            return
        if p == "/points.json":      # таб «Тюнинг весов»: живые веса tactics read-only, вне root-папки
            self._points()
            return
        if p == "/retrain_status":   # кнопка «переобучить и бои»: живой прогресс фонового прогона
            self._retrain_status()
            return
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/points_enabled":
            self._points_enabled()
            return
        if path == "/retrain":
            self._retrain()
            return
        self.send_error(404)

    def _status_running_fresh(self):
        """Чей-то прогон ещё жив: running=true в статус-файле и он обновлён < 10 мин назад."""
        try:
            st = json.load(open(STATUS, encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return bool(st.get("running")) and (time.time() - os.path.getmtime(STATUS)) < 600

    def _retrain(self):
        """Старт фона run_pipeline.py (обучение→бои→парсинг). Не блокирует запрос; сразу 200.
        Повторный клик, пока живой прогон, → 409 (чтобы не плодить конкурентные GPU-джобы)."""
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            req = json.loads(self.rfile.read(n).decode("utf-8")) if 0 < n < 4096 else {}
            run = (req.get("run") or DEFAULT_RUN).strip()
        except Exception as e:
            self._json({"ok": False, "err": "плохой запрос: %r" % (e,)}, 400)
            return
        proc = _PIPELINE["proc"]
        if proc is not None and proc.poll() is None:
            self._json({"ok": False, "err": "прогон уже запущен на этом сервере"}, 409)
            return
        if self._status_running_fresh():
            self._json({"ok": False, "err": "прогон уже идёт (retrain_status.json свежий)"}, 409)
            return
        try:
            logf = open(RUNLOG, "a", encoding="utf-8", errors="replace")
            _PIPELINE["proc"] = subprocess.Popen([sys.executable, PIPELINE, "--run", run],
                                                 cwd=SERVER, stdout=logf, stderr=subprocess.STDOUT,
                                                 stdin=subprocess.DEVNULL,
                                                 creationflags=_NEW_PROCESS_GROUP)
            self._json({"ok": True, "run": run, "pid": _PIPELINE["proc"].pid})
        except Exception as e:
            self._json({"ok": False, "err": repr(e)}, 500)

    def _retrain_status(self):
        """Отдать retrain_status.json как есть; если файла нет — состояние idle."""
        try:
            self._json(json.load(open(STATUS, encoding="utf-8")))
        except FileNotFoundError:
            self._json({"stage": "idle", "pct": 0, "message": "прогон не запускался",
                        "running": False, "done": False, "error": None})
        except (OSError, ValueError) as e:
            self._json({"stage": "error", "pct": 0, "message": repr(e),
                        "running": False, "done": False, "error": repr(e)}, 500)

    def end_headers(self):
        # viewer.html — это документ, браузер кэширует его даже без ?ts=; из-за этого
        # правки табов (например, чекбоксы) не появлялись до Ctrl+F5. Отключаем кэш для
        # ВСЕХ ответов. Не дублируем заголовок, если эндпоинт уже сам прислал Cache-Control.
        buf = self._headers_buffer or []
        if not any(h.lower().startswith(b"cache-control") for h in buf):
            self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _points_enabled(self):
        """Чекбокс «вкл» с таба «Награды и штрафы»: поменять только tactics.<section>.<key>.enabled.
        Читает файл, правит единственный путь и пишет обратно (прочие ключи/порядок сохраняются).
        Временный файл + os.replace — чтобы шейпер не увидел полфайла на hot-reload."""
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            if not 0 < n < 4096:
                raise ValueError("bad content-length")
            req = json.loads(self.rfile.read(n).decode("utf-8"))
            section, key, flag = req["section"], req["key"], bool(req["enabled"])
            if section not in ("tags", "base") or not isinstance(key, str) or not key:
                raise ValueError("bad section/key")
        except Exception as e:
            self._json({"ok": False, "err": "плохой запрос: %r" % (e,)}, 400)
            return
        with _PLOCK:
            try:
                data = json.load(open(POINTS, encoding="utf-8"))
                sec = data.setdefault("tactics", {}).setdefault(section, {})
                if key not in sec:
                    self._json({"ok": False, "err": "нет ключа tactics.%s.%s в points.json" % (section, key)}, 404)
                    return
                entry = sec[key] if isinstance(sec[key], dict) else {"value": sec[key], "enabled": True}
                entry["enabled"] = flag
                sec[key] = entry
                tmp = POINTS + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.write("\n")
                os.replace(tmp, POINTS)
                print("[points_enabled] tactics.%s.%s.enabled=%s" % (section, key, flag))
                self._json({"ok": True, "section": section, "key": key, "enabled": flag})
            except Exception as e:                      # не вешать сервер из-за записи
                self._json({"ok": False, "err": repr(e)}, 500)

    def _points(self):
        fp = os.path.normpath(os.path.join(HERE, "..", "..", "points.json"))
        try:
            data, code = open(fp, "rb").read(), 200
        except OSError as e:
            data, code = repr(e).encode("utf-8"), 404
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _refresh(self):
        code, out = 0, ""
        if not _LOCK.acquire(blocking=False):
            code, out = 409, "парсер уже запущен — подожди"
        else:
            try:
                p = subprocess.run([sys.executable, PARSE], capture_output=True,
                                   text=True, timeout=300, cwd=HERE)
                code = p.returncode
                out = ((p.stdout or "") + (("\n" + p.stderr) if p.stderr else ""))[-2000:]
            except Exception as e:                  # не вешать сервер из-за парсера
                code, out = -1, repr(e)
            finally:
                _LOCK.release()
        body = json.dumps({"ok": code == 0, "code": code, "out": out},
                          ensure_ascii=False).encode("utf-8")
        self.send_response(200 if code == 0 else 500)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        print("[refresh] code=%s | %s" % (code, out.strip().splitlines()[-1] if out else ""))

    def log_message(self, fmt, *a):                 # тише: только строки /refresh выше
        if self.path and "/refresh" in str(self.path):
            return


if __name__ == "__main__":
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("[serve] http://127.0.0.1:%d/viewer.html  (root=%s, /refresh -> parse_traces.py)"
          % (PORT, HERE))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
