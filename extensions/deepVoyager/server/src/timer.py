import time
from contextlib import contextmanager

_timers = {}
_logs = []


def _now():
    return time.strftime("%H:%M:%S", time.localtime())


def start(label: str, note: str = ""):
    _timers[label] = time.time()
    if note:
        print(f"[{_now()}] {label} start - {note}")


def stop(label: str):
    if label in _timers:
        elapsed = time.time() - _timers[label]
        print(f"[{_now()}] {label} ({elapsed:.2f}s)")
        _logs.append((label, _now(), elapsed))
        del _timers[label]
        return elapsed
    return 0


def lap(label: str, note: str = ""):
    if label in _timers:
        elapsed = time.time() - _timers[label]
        note_str = f" - {note}" if note else ""
        print(f"[{_now()}] {label} ({elapsed:.2f}s){note_str}")


@contextmanager
def measure(label: str):
    start(label)
    try:
        yield
    finally:
        stop(label)


def get_summary():
    return _logs


def reset():
    _timers.clear()
    _logs.clear()