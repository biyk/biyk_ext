# src/browser.py — порт из DeepWeb; пути/порт CDP вынесены в переменные окружения (.env)
import json
import subprocess
import sys
import os
import socket
import time
import urllib.request
import websocket
from src.timer import start, stop, lap, measure

CDP_PORT = int(os.getenv("CDP_PORT", "9222"))
BRAVE_PATH = os.getenv(
    "BRAVE_PATH",
    r"C:\Program Files\BraveSoftware\Brave-Browser-Beta\Application\brave.exe",
)
# Профиль браузера с сессией DeepSeek: по умолчанию ./profile рядом с server/, можно задать свой через .env
PROFILE_DIR = os.getenv(
    "DEEPSEEK_PROFILE_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "profile")),
)


def is_port_open(port: int) -> bool:
    """Проверяет, открыт ли порт CDP."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def get_cdp_targets():
    """Получает список CDP targets через HTTP endpoint."""
    req = urllib.request.Request(f"http://localhost:{CDP_PORT}/json")
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.load(resp)


def send_cdp_command(ws, method, params=None, msg_id=1, timeout=120):
    """Отправляет CDP команду через WebSocket и возвращает ответ."""
    cmd = {"id": msg_id, "method": method, "params": params or {}}
    ws.settimeout(timeout)
    ws.send(json.dumps(cmd))
    while True:
        raw = ws.recv()
        response = json.loads(raw)
        if response.get("id") == msg_id:
            return response


def navigate_to_url(ws_url, url):
    """Переходит по URL в текущей вкладке через CDP."""
    ws = websocket.create_connection(ws_url, timeout=30)
    resp = send_cdp_command(ws, "Page.navigate", {"url": url})
    ws.close()
    return resp


def _is_chat_page(target_url: str, desired_url: str) -> bool:
    """Проверяет что URL страницы — это именно чат DeepSeek, а не логин."""
    target = target_url.rstrip("/")
    desired = desired_url.rstrip("/")
    if target == desired:
        return True
    if target.startswith(desired + "/") and "/sign" not in target:
        return True
    return False


def get_page_ws_url(url: str) -> str:
    """Получает WebSocket URL для страницы. Запускает браузер если нужно."""
    start("ensure_browser")
    ensure_browser_running(url)
    stop("ensure_browser")
    
    start("get_cdp_targets")
    targets = get_cdp_targets()
    lap("get_cdp_targets")
    page_targets = [t for t in targets if t.get("type") == "page"]
    
    start("find_url")
    existing = next((t for t in page_targets if _is_chat_page(t.get("url", ""), url)), None)
    lap("find_url")
    
    if existing:
        ws_url = existing["webSocketDebuggerUrl"]
    elif page_targets:
        ws_url = page_targets[0]["webSocketDebuggerUrl"]
        start("navigate")
        navigate_to_url(ws_url, url)
        lap("navigate")
        targets = get_cdp_targets()
        existing = next((t for t in targets if t.get("type") == "page" and _is_chat_page(t.get("url", ""), url)), None)
        ws_url = existing["webSocketDebuggerUrl"]
    else:
        browser_target = next((t for t in targets if t.get("type") == "browser"), targets[0])
        ws = websocket.create_connection(browser_target["webSocketDebuggerUrl"], timeout=10)
        send_cdp_command(ws, "Target.createTarget", {"url": url})
        ws.close()
        targets = get_cdp_targets()
        existing = next((t for t in targets if t.get("type") == "page" and _is_chat_page(t.get("url", ""), url)), None)
        ws_url = existing["webSocketDebuggerUrl"]

    return ws_url


def ensure_browser_running(url="https://chat.deepseek.com"):
    """Проверяет и запускает Brave Browser с CDP если нужно."""
    with measure("browser_launch"):
        if not is_port_open(CDP_PORT):
            print("Запуск Brave Browser с удалённой отладкой...")
            user_data_dir = PROFILE_DIR
            cmd = [
                BRAVE_PATH,
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-allow-origins=*",
                "--start-maximized",
                "--new-window",
                url
            ]
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # Ждём пока браузер откроет CDP порт
            start("wait_port_open")
            for _ in range(20):
                time.sleep(1)
                lap("wait_port_open")
                if is_port_open(CDP_PORT):
                    break
            else:
                raise RuntimeError("Не удалось дождаться запуска браузера.")
            stop("wait_port_open")

            print("Браузер запущен.")


def open_tab(url: str):
    """Открывает URL в браузере. Создаёт вкладку или использует существующую."""
    get_page_ws_url(url)
    print(f"Вкладка: {url}")