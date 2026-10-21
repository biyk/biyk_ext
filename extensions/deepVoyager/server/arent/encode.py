# arent/encode.py — наблюдение + слоты -> векторы фиксированной длины.
#
# Состояние — один вектор (me | враги | союзники | оружие | патч поля), действия — по
# вектору на слот в каждой из трёх групп. Порядок и состав признаков задаёт
# spec.*_FEATURES: здесь значения идут в том же порядке, тест сверяет длины, иначе
# размерности сети и данных разъедутся молча. Пустой слот — нули, кроме slotIndex:
# сеть не должна путать «враг в нулевой клетке» с «врага нет».
from typing import Any, Dict, List

from planner.context import BattleContext
from planner.geometry import cell_distance
from arent import spec
from arent.observe import has_los, sight_segments

D = spec.D_SCALE


def _r(value: float) -> float:
    return round(float(value), 3)


def _empty(size: int, index: int, total: int) -> List[float]:
    """Пустой слот: активен = 0, индекс свой, признаки нулевые."""
    out = [0.0] * size
    out[1] = _r((index + 1) / total)
    return out


def _slot(active: bool, index: int, total: int) -> List[float]:
    return [1.0 if active else 0.0, _r((index + 1) / total)]


def _group(vecs: List[List[float]], total: int, size: int) -> List[List[float]]:
    """Дослать пустых слотов до фиксированного размера (последний — «никого/ничего»)."""
    out = list(vecs[:total])
    while len(out) < total:
        out.append(_empty(size, len(out), total))
    return out


def me_features(obs: Dict[str, Any]) -> List[float]:
    me, enemies = obs["me"], obs["enemies"]
    charged = sum(1 for e in enemies if e["alive"] and e["canReachMe"])
    nearest = min([e["dist"] for e in enemies if e["alive"]] or [D])
    return [
        1.0 if me["hp"] > 0 else 0.0, _r(me["hp"] / spec.HP_SCALE),
        _r(me["hpMax"] / spec.HP_SCALE), _r(me["hp"] / me["hpMax"]) if me["hpMax"] else 0.0,
        _r(me["ac"] / 20), _r(me["speedCells"] / 8), _r(1.0),
        _r(me["dmgAvg"] / spec.DMG_SCALE), _r(me["toHit"] / 5), _r(me["reachCells"]),
        _r(me["rangeCells"] / 24), _r(1.0), _r(0.0), _r(me["enemiesAlive"]),
        _r(me["alliesAlive"]), _r(charged), _r(me["incomingAvg"] / spec.DMG_SCALE),
        _r(charged / max(1, me["enemiesAlive"])), _r(nearest / D), _r(me["cr"] / 4),
        # v2 team combat (значения приходят из observe/sim; до коммита №2 — 0):
        # доля союзников, уже сходивших в раунде; LOS до ближайшего врага; доля пути до него;
        # число стен в окне (норма /16). order == spec.ME_FEATURES.
        _r(me.get("alliesActedFraction", 0.0)), 1.0 if me.get("hasLosToNearestEnemy") else 0.0,
        _r(me.get("pathLenFrac", 0.0)), _r(me.get("wallsInView", 0.0) / 16.0),
    ]


def entity_slot(e: Dict[str, Any], index: int, total: int, target_id: Any, melee: float) -> List[float]:
    """Слот цели (он же признак врага в состоянии): геометрия, живучесть и угроза."""
    return _slot(bool(e["alive"]), index, total) + [
        _r(e["dx"] / D), _r(e["dy"] / D), _r(e["dist"] / D),
        _r(e["hp"] / e["hpMax"]) if e["hpMax"] else _r(e["hp"] / spec.HP_SCALE),
        _r(e["ac"] / 20), _r(e["speedCells"] / 8), _r(e["dmgAvg"] / spec.DMG_SCALE),
        _r(e["toHit"] / 5), _r(e["reachCells"]), _r(e["rangeCells"] / 24),
        1.0 if e["los"] else 0.0, 1.0 if e["canHitMe"] else 0.0,
        1.0 if e["canReachMe"] else 0.0, 1.0 if e["dist"] <= melee else 0.0,
        1.0 if e["hostile"] and e["dist"] <= 24 else 0.0, 1.0 if e["id"] == target_id else 0.0,
        0.0 if e["alive"] else 1.0, _r(e["dmgToMe"] / spec.DMG_SCALE),
        # v2: индекс инициативы (норма по K_TARGETS) и «ходит следующим после актора».
        _r(e.get("initiativeIndex", 0) / spec.K_TARGETS), 1.0 if e.get("isNextToAct") else 0.0,
    ]


def ally_slot(a: Dict[str, Any], index: int, total: int) -> List[float]:
    return _slot(True, index, total) + [
        _r(a["dx"] / D), _r(a["dy"] / D), _r(a["dist"] / D),
        _r(a["hp"] / a["hpMax"]) if a["hpMax"] else 0.0, _r(a["ac"] / 20),
        _r(a["speedCells"] / 8), _r(a["dmgAvg"] / spec.DMG_SCALE), 1.0 if a["los"] else 0.0,
        1.0 if a["dist"] <= 2 else 0.0, _r(0.0),
        # v2: индекс инициативы союзника (норма по K_ALLIES).
        _r(a.get("initiativeIndex", 0) / spec.K_ALLIES),
    ]


def weapon_slot(w: Dict[str, Any], index: int, total: int) -> List[float]:
    if not w:
        return _empty(len(spec.WEAPON_FEATURES), index, total)
    return _slot(True, index, total) + [
        _r(w["dmgAvg"] / spec.DMG_SCALE), _r(w["toHit"] / 5),
        1.0 if not w["ranged"] else 0.0, _r(w["sureCells"] / 24), _r(w["doubtCells"] / 24),
        1.0 if w["reachesAny"] else 0.0, 1.0 if w["bestModeSure"] else 0.0,
        1.0 if w["ranged"] else 0.0, 1.0 if w["thrown"] else 0.0,
    ]


def grid_features(obs: Dict[str, Any]) -> List[float]:
    """Патч поля плоским списком: '.'=0, '#'=1, 'E'=2, 'A'=3, 'T'=4, '@'=5."""
    rows, r = obs["grid"], spec.PATCH_R
    flat = []
    for dr in range(-r, r + 1):
        line = rows[dr + r] if 0 <= dr + r < len(rows) else ""
        for dc in range(-r, r + 1):
            letter = line[dc + r] if 0 <= dc + r < len(line) else "#"
            flat.append(spec.GRID_LETTERS.get(letter, 1.0))
    return flat


def state(obs: Dict[str, Any]) -> List[float]:
    """Вектор состояния: порядок групп = порядок в spec.dims()."""
    melee, target = obs["me"]["reachCells"], obs["target"]
    enemies = _group([entity_slot(e, i, spec.K_TARGETS, target, melee)
                      for i, e in enumerate(obs["enemies"])],
                     spec.K_TARGETS, len(spec.ENEMY_FEATURES))
    allies = _group([ally_slot(a, i, spec.K_ALLIES) for i, a in enumerate(obs["allies"])],
                    spec.K_ALLIES, len(spec.ALLY_FEATURES))
    weapons = _group([weapon_slot(w, i, spec.K_WEAPONS + 1) for i, w in enumerate(obs["weapons"])],
                     spec.K_WEAPONS + 1, len(spec.WEAPON_FEATURES))
    return (me_features(obs) + [v for s in enemies for v in s]
            + [v for s in allies for v in s] + [v for s in weapons for v in s]
            + grid_features(obs))


def target_vectors(obs: Dict[str, Any], slots: Any) -> List[List[float]]:
    """Слоты целей: те же признаки врагов, что в состоянии, плюс «не стрелять» последним."""
    total = spec.K_TARGETS + 1
    melee = obs["me"]["reachCells"]
    vecs = [entity_slot(e, i, total, obs["target"], melee) for i, e in enumerate(slots.targets)]
    return _group(vecs, total, len(spec.ENEMY_FEATURES))


def weapon_vectors(obs: Dict[str, Any], slots: Any) -> List[List[float]]:
    """Слоты «чем бить»: оружие героя + «не атаковать» последним слотом."""
    total = spec.K_WEAPONS + 1
    return _group([weapon_slot(w, i, total) for i, w in enumerate(slots.weapons)],
                  total, len(spec.WEAPON_FEATURES))


def cell_vectors(ctx: BattleContext, obs: Dict[str, Any], slots: Any) -> List[List[float]]:
    """Слоты клеток хода: дистанции до врагов, есть ли из клетки атака и что за неё ответит."""
    enemies = [e for e in obs["enemies"] if e["hostile"] and e["alive"]]
    at = lambda e: (ctx.src_cell[0] + e["dy"], ctx.src_cell[1] + e["dx"])   # noqa: E731
    reach = {(ctx.src_cell[0] + c["dy"], ctx.src_cell[1] + c["dx"]) for c in slots.cells}
    occupied = {at(e) for e in obs["enemies"] + obs["allies"] + obs["others"]}
    segments = sight_segments(ctx)
    total, size = spec.K_CELLS + 1, len(spec.CELL_FEATURES)
    vecs: List[List[float]] = []
    for i, c in enumerate(slots.cells[:spec.K_CELLS]):
        cell = c["cell"]
        dists = [cell_distance(cell, at(e)) for e in enemies] or [D]
        nearest = min(dists)
        sure = any(w["bestModeSure"] and nearest <= w["sureCells"] + 0.5 for w in obs["weapons"])
        doubt = any(nearest <= w["doubtCells"] + 0.5 for w in obs["weapons"])
        threat = [e for e in enemies if cell_distance(cell, at(e)) <= e["reachCells"]
                  + e["speedCells"] + 1]
        los_any = any(has_los(ctx, cell, at(e), segments) for e in enemies)
        free = sum(1 for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                   if (dr or dc) and (cell[0] + dr, cell[1] + dc) in reach) / 8.0
        vecs.append(_slot(True, i, total) + [
            _r(c["dx"] / D), _r(c["dy"] / D), _r(c["dist"] / D),
            _r(len(c["dirs"]) / max(1, ctx.speed_steps)), 1.0 if not c["dirs"] else 0.0,
            _r(free), _r(nearest / D), 1.0 if doubt else 0.0, 1.0 if sure else 0.0,
            1.0 if doubt and not sure else 0.0, 1.0 if los_any else 0.0, _r(len(threat)),
            _r(sum(e["dmgToMe"] for e in threat) / spec.DMG_SCALE), 1.0 if not los_any else 0.0,
            _r(sum(1 for e in enemies if e["hpMax"] and e["hp"] / e["hpMax"] < 0.5)
               / max(1, len(enemies))),
            _r(sum(1 for o in occupied if cell_distance(cell, o) <= 2) / 4.0),
        ])
    return _group(vecs, total, size)


def _mask(real: int, total: int, none_slot: bool) -> List[int]:
    """Маска группы: реальные слоты = 1, досланные = 0, «никого/ничего» — 1 или 0."""
    out = [1] * min(real, total - 1) + [0] * max(0, total - 1 - min(real, total - 1))
    return out + ([1] if none_slot else [0])


def encode(ctx: BattleContext, obs: Dict[str, Any], slots: Any, label: Dict[str, int],
           value: float = 0.0, meta: Dict[str, Any] = None) -> Dict[str, Any]:
    """Наблюдение + слоты + разметка учителя -> один пример выборки (JSON-пригодный)."""
    sample = observation(ctx, obs, slots)
    sample["y"] = {"cell": label["cell"], "target": label["target"], "weapon": label["weapon"]}
    sample["value"] = _r(max(-3.0, min(3.0, value / spec.VALUE_SCALE)))
    sample["meta"] = dict(meta or {}, src=ctx.src_id, cell=list(ctx.src_cell))
    return sample


def observation(ctx: BattleContext, obs: Dict[str, Any], slots: Any) -> Dict[str, Any]:
    """Векторы состояния и слотов без разметки: из этого же играет модель (play.py)."""
    return {
        "schema": spec.SCHEMA, "state": state(obs),
        "cells": cell_vectors(ctx, obs, slots),
        "targets": target_vectors(obs, slots),
        "weapons": weapon_vectors(obs, slots),
        "mask": {"cells": _mask(slots.n_cells, spec.K_CELLS + 1, False),
                 "targets": _mask(len(slots.targets), spec.K_TARGETS + 1, True),
                 "weapons": _mask(len(slots.weapons), spec.K_WEAPONS + 1, True)},
    }
