# arent/capture.py — сбор состояний, в которых бой оказывается на самом деле.
#
# Планировщик получает на /plan ровно то наблюдение, из которого dataset строит примеры,
# поэтому запрос бойца и есть будущий обучающий пример. Здесь он и складывается рядом с
# ответом учителя, чтобы `gen` разметил его без ручного переноса файлов.
#
# Дубли одного и того же состояния не множим: в имени файла лежит хэш payload, и по нему
# видно, что состояние уже размечено. Каталог ограничен по размеру (MAX_FILES), иначе
# долгий бой превратил бы data/payloads в гору одинаковых снимков.
#
# Выключается одной переменной окружения: ARENT_CAPTURE=0 (по умолчанию сбор включён).
import glob
import hashlib
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from arent import paths

MAX_FILES = 200                       # старше — удаляем, каталог не должен расти бесконечно
OFF_VALUES = ("0", "false", "no", "off")


def enabled() -> bool:
    """Собр включён, если ARENT_CAPTURE не выставлен в off: запись дешёвая и молчаливая."""
    return os.getenv("ARENT_CAPTURE", "1").strip().lower() not in OFF_VALUES


def key_of(payload: Dict[str, Any]) -> str:
    """Хэш состояния: один и тот же запрос из клиента даёт одно и то же имя."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def files() -> List[str]:
    """Снимки от старого к новому (по времени записи, при равных — по имени)."""
    directory = paths.capture_dir()
    if not os.path.isdir(directory):
        return []
    paths_ = glob.glob(os.path.join(directory, "*.json"))
    return sorted(paths_, key=lambda p: (os.path.getmtime(p), os.path.basename(p)))


def known_keys() -> set:
    return {os.path.splitext(os.path.basename(path))[0].rsplit("_", 1)[-1] for path in files()}


def capture(payload: Dict[str, Any], plan: Any = None, event: str = "") -> Optional[str]:
    """Записать состояние формата /plan (и ответ на него); None, если запись не нужна."""
    if not enabled() or not isinstance(payload, dict) or not payload:
        return None
    key = key_of(payload)
    if key in known_keys():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = paths.file_in(paths.ensure(paths.capture_dir()), f"cap_{stamp}_{key}.json")
    record = {"captured": datetime.now().isoformat(timespec="seconds"), "event": event,
              "key": key, "payload": payload, "plan": plan}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, separators=(",", ":"))
    prune()
    return path


def prune(limit: Optional[int] = None) -> List[str]:
    """Удалить самые старые снимки сверх limit; вернуть удалённые пути.

    MAX_FILES читается в момент вызова (а не по умолчанию аргумента), иначе подкрутить
    лимит в тесте или конфиге было невозможно.
    """
    limit = MAX_FILES if limit is None else limit
    removed: List[str] = []
    overflow = files()[:-limit] if limit > 0 else []
    for path in overflow:
        try:
            os.remove(path)
        except OSError:                                 # файл мог быть открыт: не ломаем запрос
            continue
        removed.append(path)
    return removed
