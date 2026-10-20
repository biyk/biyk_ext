# playground/arena.py — виртуальная арена -> payload, совместимый с /plan (пункт 5).
#
# Арена описывает сцену так, как её присылает Foundry, но человеческим языком:
# токены задаются клетками, герой — скоростью и списком оружия, враги — опциональными
# полями симуляции (speed/damage/reachFt/hitChance). Битая арена падает здесь же, с
# именем арены в тексте ошибки, а не KeyError в глубине разбора.
import json
import os
from typing import Any, Dict, List

ARENAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arenas")
DEFAULT_SCENE = {"width": 500, "height": 500, "gridSize": 50}
# поля токена, которые /plan читает «как есть» для симуляции чужих ходов
SIM_FIELDS = ("speed", "damage", "reachFt", "hitChance")


def arena_file(name: str) -> str:
    return os.path.join(ARENAS_DIR, f"{name}.json")


def list_arenas() -> List[str]:
    """Имена арен в каталоге arenas/ (без расширения), по алфавиту."""
    try:
        files = os.listdir(ARENAS_DIR)
    except OSError:
        return []
    return sorted(os.path.splitext(f)[0] for f in files if f.endswith(".json"))


ARENA_NAMES: List[str] = list_arenas()


def _require(raw: Dict[str, Any], key: str, where: str) -> Any:
    if key not in raw or raw[key] in (None, "", []):
        raise ValueError(f"арена {where}: нет обязательного поля {key!r}")
    return raw[key]


def _position(tok: Dict[str, Any], grid: int, where: str):
    """Клетка [row, col] или точка xy в пикселях -> левый верхний угол токена."""
    if "cell" in tok:
        row, col = tok["cell"]
        return int(col) * grid, int(row) * grid
    if "xy" in tok:
        x, y = tok["xy"]
        return int(x), int(y)
    raise ValueError(f"арена {where}: токен {tok.get('id')!r} без cell и без xy")


def _npc(tok: Dict[str, Any], grid: int, where: str) -> Dict[str, Any]:
    """Запись арены -> запись npcs[] формата api.getAllData()."""
    tid = str(_require(tok, "id", where))
    size = int(tok.get("size", grid))
    x, y = _position(tok, grid, where)
    hp = int(tok.get("hp", 10))
    npc: Dict[str, Any] = {
        "id": tid, "name": str(tok.get("name", tid)),
        "x": x, "y": y, "width": size, "height": size,
        "center": {"x": x + size / 2, "y": y + size / 2},
        "disposition": int(tok.get("disposition", 0)),
        "hp": {"current": hp, "max": int(tok.get("hpMax", hp)), "temp": 0},
    }
    for key in SIM_FIELDS:
        if tok.get(key) is not None:
            npc[key] = tok[key]
    return npc


def _wall(raw: Dict[str, Any], index: int, where: str) -> Dict[str, Any]:
    points = _require(raw, "points", f"{where}/wall#{index}")
    for side in ("A", "B"):
        if not isinstance(points.get(side), dict):
            raise ValueError(f"арена {where}: стена #{index} без points.{side}")
    wall = {"id": str(raw.get("id", f"w{index}")), "points": points, "move": int(raw.get("move", 1)),
            "sight": int(raw.get("sight", 1)), "type": "wall", "door": None,
            "closed": False, "locked": False}
    return wall


def build_payload(raw: Dict[str, Any], where: str) -> Dict[str, Any]:
    """Описание арены -> запрос, который понимает эндпоинт /plan."""
    scene = {**DEFAULT_SCENE, **(raw.get("scene") or {})}
    grid = int(scene["gridSize"])
    hero = _require(raw, "hero", where)
    tokens = _require(raw, "tokens", where)
    src_id = str(_require(hero, "id", where))
    npcs = [_npc(tok, grid, where) for tok in tokens]
    if not any(n["id"] == src_id for n in npcs):
        raise ValueError(f"арена {where}: герой {src_id!r} не среди tokens[]")
    return {
        "src": src_id, "token": raw.get("target"), "mode": raw.get("mode", "direct"),
        "speed": hero.get("speed", 30), "weapons": _require(hero, "weapons", where),
        "data": {"scene": scene, "npcs": npcs,
                 "walls": [_wall(w, i, where) for i, w in enumerate(raw.get("walls") or [])]},
    }


def load_raw(name: str) -> Dict[str, Any]:
    """JSON арены с проверкой, что файл — объект."""
    path = arena_file(name)
    if name not in ARENA_NAMES:
        raise ValueError(f"арена {name!r} не найдена в {ARENAS_DIR}")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"арена {name!r}: ожидается объект с hero/tokens")
    return raw


def load_arena(name: str) -> Dict[str, Any]:
    """Арена -> payload для /plan; невалидная сцена — ValueError с именем арены."""
    from planner.context import BattleContext        # здесь, а не наверху: нет цикла
    raw = load_raw(name)
    payload = build_payload(raw, name)
    try:
        BattleContext.from_payload(payload)
    except ValueError as e:
        raise ValueError(f"арена {name!r}: {e}") from e
    return payload
