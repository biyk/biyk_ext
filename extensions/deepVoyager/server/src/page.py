import time
import websocket
from src.browser import send_cdp_command
from src.timer import start, stop, lap, measure


def click_element(ws, selector: str):
    send_cdp_command(ws, "Runtime.evaluate", {"expression": f"document.querySelector('{selector}').click()"})


def get_attribute(ws, selector: str, attr: str) -> str:
    result = send_cdp_command(ws, "Runtime.evaluate", {"expression": f"(document.querySelector('{selector}') || {{}}).getAttribute('{attr}')"})
    return result.get("result", {}).get("result", {}).get("value", "")


def wait_for_element(ws, selector: str, timeout: int = 10) -> bool:
    start("wait_element", f"selector={selector}")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            resp = send_cdp_command(ws, "Runtime.evaluate", {
                "expression": f"!!document.querySelector('{selector}')"
            })
            if resp.get("result", {}).get("result", {}).get("value"):
                stop("wait_element")
                return True
        except Exception:
            pass
        time.sleep(0.5)
    stop("wait_element")
    return False


def set_textarea(ws, selector: str, text: str):
    start("set_textarea_clear")
    send_cdp_command(ws, "Runtime.evaluate", {"expression": f"document.querySelector('{selector}').value = ''"})
    stop("set_textarea_clear")
    time.sleep(0.5)
    start("set_textarea_focus")
    send_cdp_command(ws, "Runtime.evaluate", {"expression": f"document.querySelector('{selector}').focus()"})
    stop("set_textarea_focus")
    time.sleep(0.5)
    start("set_textarea_insert")
    send_cdp_command(ws, "Input.insertText", {"text": text})
    stop("set_textarea_insert")


def type_text(ws, selector: str, text: str):
    start("type_text", f"len={len(text)}")
    wait_for_element(ws, selector)
    set_textarea(ws, selector, text)
    stop("type_text")


def press_enter_and_verify(ws, selector: str) -> bool:
    start("press_enter")
    send_cdp_command(ws, "Input.dispatchKeyEvent", {"key": "Enter", "type": "keyDown"})
    send_cdp_command(ws, "Input.dispatchKeyEvent", {"key": "Enter", "type": "keyUp"})
    start("enter_verify_pause")
    time.sleep(0.2)
    stop("enter_verify_pause")
    result = send_cdp_command(ws, "Runtime.evaluate", {
        "expression": f"document.querySelector('{selector}').value"
    })
    remaining = result.get("result", {}).get("result", {}).get("value", "")
    stop("press_enter")
    return remaining == ""


def get_last_response(ws, timeout: int = 300) -> str:
    start("get_response_polling")
    start_time = time.time()
    iteration = 0
    while time.time() - start_time < timeout:
        iteration += 1
        result = send_cdp_command(ws, "Runtime.evaluate", {
            "expression": """
                (function() {
                   const items = document.querySelector('.ds-virtual-list-items');
                    if (!items) return null;
                    const messages = items.querySelectorAll('.ds-message');
                    if (!messages.length) return null;
                    const lastMsg = messages[messages.length - 1];
                    const parent = lastMsg.parentElement;
                    if (!parent) return null;
                    const flex = Array.from(parent.children).find(c => c.classList.contains('ds-flex'));
                    if (!flex) return null;
                    const msgEl = Array.from(lastMsg.children).find(c => c.classList.contains('ds-markdown')) || lastMsg;
                    return msgEl.innerText.trim();
                })()
            """
        })
        text = result.get("result", {}).get("result", {}).get("value")
        if text:
            lap("get_response_polling", f"iter={iteration} got {len(text)} chars")
            stop("get_response_polling")
            return text
        time.sleep(1)
    lap("get_response_polling", "timeout")
    stop("get_response_polling")
    return ""


def select_expert(ws) -> bool:
    with measure("select_expert"):
        with measure("wait_model_type"):
            wait_for_element(ws, '[data-model-type]')
        start("select_expert_pause")
        time.sleep(1)
        stop("select_expert_pause")
        with measure("click_expert"):
            click_element(ws, '[data-model-type="expert"]')
        start("select_expert_verify_pause")
        time.sleep(1)
        stop("select_expert_verify_pause")
        with measure("check_expert"):
            checked = get_attribute(ws, '[data-model-type="expert"]', 'aria-checked')
        print(f"Эксперт выбран: {checked}")
        return checked == "true"


def send_message(ws, text: str) -> str:
    with measure("send_message"):
        with measure("type_text"):
            type_text(ws, 'textarea', text)
        with measure("press_enter"):
            sent = press_enter_and_verify(ws, 'textarea')
        print(f"Текст отправлен: {sent}")
        with measure("get_response"):
            response = get_last_response(ws)
        return response