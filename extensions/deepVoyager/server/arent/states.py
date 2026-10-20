# arent/states.py — варианты состояний из одного снимка боя.
#
# Живой дамп — это одна точка в пространстве состояний: полный состав, все живы,
# все на старте. Чтобы учить модель не «запоминать арену», а обобщать, состояния
# дополняем:
#  • src меняем на любой токен, у которого в npcs[] есть своё weapons[] (живой снимок
#    присылает вооружение каждого токена — для арен playground src остаётся героем);
#  • прогоняем несколько случайных раундов через Simulation (герой — случайный ход из
#    hero_options(), враги — жадное сближение), и переставляем клетки/hp в payload.
# Планировщик при этом видит честный бой: убитые падают по hp, раненные меняют цену риска.
import copy
import random
from typing import Any, Dict, Iterator, List, Optional, Tuple

from planner.context import BattleContext
from planner.geometry import Cell
from planner.sim import Simulation

Meta = Dict[str, Any]


def npc_map(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """id токена -> его сырая запись npcs[] (там weapons/ac/toHit этого токена)."""
    return {str(n.get("id")): n for n in (payload.get("data") or {}).get("npcs") or []}


def src_candidates(payload: Dict[str, Any]) -> List[str]:
    """Кто может ходить: исходный src плюс токены, чьё вооружение прислали."""
    out = [payload.get("src")]
    for token, raw in npc_map(payload).items():
        if raw.get("weapons") and token != payload.get("src"):
            out.append(token)
    return [t for t in out if t]


def rebuild(base: Dict[str, Any], src_id: str, cells: Optional[Dict[str, Cell]] = None,
            hp: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Тот же бой, но с другим src и (опционально) другими клетками и hp."""
    payload = copy.deepcopy(base)
    grid = int(payload["data"]["scene"]["gridSize"])
    npcs = npc_map(payload)
    for token, raw in npcs.items():
        if cells and token in cells:
            row, col = cells[token]
            raw["x"], raw["y"] = int(col * grid), int(row * grid)
            raw["center"] = {"x": raw["x"] + raw["width"] / 2, "y": raw["y"] + raw["height"] / 2}
        if hp and token in hp:
            raw["hp"] = {**(raw.get("hp") or {}), "current": int(max(0, round(hp[token])))}
    chosen = npc_map(payload).get(src_id) or {}
    payload["src"] = src_id
    payload["token"] = None
    payload["speed"] = chosen.get("speed") or base.get("speed") or 30
    payload["weapons"] = chosen.get("weapons") or base.get("weapons") or []
    return payload


def playout(payload: Dict[str, Any], rng: random.Random, rounds: int
            ) -> Tuple[Dict[str, Cell], Dict[str, float]]:
    """Случайная развязка на N раундов: клетки и hp всех токенов после неё."""
    state = Simulation.of(BattleContext.from_payload(payload))
    for _ in range(max(1, rounds)):
        options = state.hero_options()
        actions = rng.choice(options) if options else []
        state, _value = state.apply_hero(actions).foes_act()
        if state.hero_dead:
            break
    return state.cells, state.hp


def variants(base: Dict[str, Any], rng: random.Random, count: int = 4, rounds_max: int = 3,
             src_ids: Optional[List[str]] = None) -> Iterator[Tuple[Dict[str, Any], Meta]]:
    """Перебор src × случайных продолжений боя — источник разнообразия выборок."""
    srcs = src_ids or src_candidates(base)
    produced = 0
    for src_id in srcs:
        for i in range(count):
            if produced >= count * len(srcs):
                return
            rounds = rng.randint(1, max(1, rounds_max)) if i else 0   # i=0 — исходное состояние
            cells = hp = None
            if rounds:
                cells, hp = playout(rebuild(base, src_id), rng, rounds)
            payload = rebuild(base, src_id, cells, hp)
            alive = BattleContext.from_payload(payload)
            if not alive.hostile_targets():        # бой окончен — размечать нечего
                continue
            produced += 1
            yield payload, {"src": src_id, "rounds": rounds, "variant": i}
