# tests/conftest.py — общий путь к пакетам сервера и фикстуры сцен.
import os
import sys

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVER_DIR)

import pytest  # noqa: E402

from planner import points  # noqa: E402
from arent import paths as arent_paths  # noqa: E402


def make_npc(npc_id, x, y, size=50, disposition=0, hp=10, name=None,
             speed=None, damage=None, reach_ft=None, hit_chance=None, initiative=None):
    """Токен size×size в клетку, координаты — левый верхний угол (как в Foundry).

    speed/damage/reach_ft/hit_chance — необязательные параметры для симуляции хода
    (пункт 5): чем бьёт этот токен, как далеко ходит и с какой вероятностью попадает.
    Не присланы — сервер берёт дефолты из points.json (старый клиент не сломан).
    """
    npc = {
        "id": npc_id, "name": name if name is not None else npc_id,
        "x": x, "y": y, "width": size, "height": size,
        "center": {"x": x + size / 2, "y": y + size / 2},
        "disposition": disposition,
        "hp": {"current": hp, "max": hp, "temp": 0},
    }
    for key, value in (("speed", speed), ("damage", damage),
                       ("reachFt", reach_ft), ("hitChance", hit_chance),
                       ("initiative", initiative)):
        if value is not None:
            npc[key] = value
    return npc


def make_wall(wall_id, ax, ay, bx, by, move=1, sight=1):
    return {
        "id": wall_id,
        "points": {"A": {"x": ax, "y": ay}, "B": {"x": bx, "y": by}},
        "type": "wall", "door": None, "closed": False, "locked": False,
        "move": move, "sight": sight,
    }


def make_weapon(wid, name="sword", damage="1d6+2", bonus=2, sure_ft=5, doubt_ft=None,
                ranged=None, properties=None):
    """Оружие в payload: уверенная и сомнительная дистанции в футах.

    У ближнего боя doubt_ft == sure_ft (5 фт, или 10 у оружия с reach).
    ranged=None — поля в payload нет (сервер выводит дальнобойность сам).
    properties — коды свойств dnd5e ('thr' метательное, 'rch' досягаемость, 'fin'…).
    """
    entry = {
        "id": wid, "name": name, "damage": damage, "attackBonus": bonus,
        "sureFt": sure_ft, "doubtFt": doubt_ft if doubt_ft is not None else sure_ft,
    }
    if ranged is not None:
        entry["ranged"] = ranged
    if properties is not None:
        entry["properties"] = list(properties)
    return entry


def make_scene_payload(walls=None, npcs=None, grid=50, weapons=None, token="B"):
    return {
        "src": "A",
        "token": token,
        "mode": "direct",
        "weapons": weapons if weapons is not None else [],
        "data": {
            "scene": {"id": "s1", "name": "test", "width": 500, "height": 500, "gridSize": grid},
            "npcs": npcs if npcs is not None else [
                make_npc("A", 0, 0, disposition=-1), make_npc("B", 450, 0, disposition=1)],
            "walls": walls if walls is not None else [],
        },
    }


@pytest.fixture(autouse=True)
def pin_default_tuning():
    """Фиксируем встроенные коэффициенты на время теста.

    Иначе правка server/points.json (её пользователь крутит под себя) меняла бы
    очки во всех тестах, где ожидаются 30/15/1.
    """
    previous = points.set_tuning(points.default_tuning())
    yield
    points.set_tuning(previous or points.default_tuning())


@pytest.fixture(autouse=True)
def keep_arent_workspace():
    """Тестовая генерация и обучение не должны писать в боевой arent/data и arent/runs."""
    before = arent_paths.workspace()
    yield
    arent_paths.set_workspace(before)


@pytest.fixture
def scene_payload():
    """Свободная сцена 10×10: враждебный A в (0,0), цель B в (9,0) — 9 шагов вправо."""
    return make_scene_payload()
