# tests/conftest.py — общий путь к пакетам сервера и фикстуры сцен.
import os
import sys

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVER_DIR)

import pytest  # noqa: E402


def make_npc(npc_id, x, y, size=50, disposition=0, hp=10):
    """Токен size×size в клетку, координаты — левый верхний угол (как в Foundry)."""
    return {
        "id": npc_id, "name": npc_id,
        "x": x, "y": y, "width": size, "height": size,
        "center": {"x": x + size / 2, "y": y + size / 2},
        "disposition": disposition,
        "hp": {"current": hp, "max": hp, "temp": 0},
    }


def make_wall(wall_id, ax, ay, bx, by, move=1, sight=1):
    return {
        "id": wall_id,
        "points": {"A": {"x": ax, "y": ay}, "B": {"x": bx, "y": by}},
        "type": "wall", "door": None, "closed": False, "locked": False,
        "move": move, "sight": sight,
    }


def make_scene_payload(walls=None, npcs=None, grid=50):
    return {
        "src": "A",
        "token": "B",
        "mode": "direct",
        "data": {
            "scene": {"id": "s1", "name": "test", "width": 500, "height": 500, "gridSize": grid},
            "npcs": npcs if npcs is not None else [
                make_npc("A", 0, 0, disposition=-1), make_npc("B", 450, 0, disposition=1)],
            "walls": walls if walls is not None else [],
        },
    }


@pytest.fixture
def scene_payload():
    """Свободная сцена 10×10: враждебный A в (0,0), цель B в (9,0) — 9 шагов вправо."""
    return make_scene_payload()
