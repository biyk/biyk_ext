import websocket
from dotenv import load_dotenv
import os
from src.browser import get_page_ws_url
from src.page import select_expert, send_message
from src.timer import measure, reset, get_summary, start, lap, stop

load_dotenv()

DEEPSEEK_URL = "https://chat.deepseek.com"
USE_EXPERT = os.getenv("DEEPSEEK_USE_EXPERT", "false").lower() == "true"


def ask(text: str) -> str:
    reset()
    with measure("ask"):
        start("get_page_ws_url")
        ws_url = get_page_ws_url(DEEPSEEK_URL)
        lap("get_page_ws_url")
        ws = websocket.create_connection(ws_url, timeout=30)
        lap("ws_connect")
        try:
            if USE_EXPERT:
                with measure("select_expert"):
                    select_expert(ws)
            response = send_message(ws, text)
        finally:
            ws.close()
    return response