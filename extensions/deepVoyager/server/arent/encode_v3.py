# arent/encode_v3.py — наблюдение схемы 3: голова move-plan вместо головы клеток.
#
# Векторы состояния/целей/оружия и значение — ровно те же, что в схеме 2 (encode.state /
# encode.target_vectors / encode.weapon_vectors): меняется ТОЛЬКО группа cells. Вместо
# «одна клетка = финальная, бьём с неё» слот головы клеток — ПЛАН ХОДА (attack_cell,end_cell)
# в бюджете движения, построенный slots_v3 из честного reach. Так «выстрелить с места и
# отойти» становится представимо одним каталогом слотов (см. arent/spec3.py, arent/slots_v3.py
# и planner/sim.py::apply_actor_seq).
#
# Структура образца совпадает с encode.encode: schema/state/cells/targets/weapons/mask/y/value/
# meta. Отличие: cells — векторы планов (ширина spec3.CELL3_FEATURES, глубина K_MOVEPLAN+1),
# а y = {plan, target, weapon} (plan вместо cell). Схема 2 в encode.py остаётся нетронутой.
from typing import Any, Dict, List

from planner.context import BattleContext
from planner.geometry import cell_distance
from arent import encode as enc
from arent import joint, spec, spec3, slots_v3
from arent.observe import has_los, sight_segments

D = spec.D_SCALE
_r = enc._r


def _enemy_cell(ctx: BattleContext, e: Dict[str, Any]):
    """Клетка врага из наблюдения: смещения dx/dy заданы относительно исходной клетки src."""
    return (ctx.src_cell[0] + e["dy"], ctx.src_cell[1] + e["dx"])


def plan_vector(ctx: BattleContext, obs: Dict[str, Any], plan: Dict[str, Any],
                index: int, total: int, segments) -> List[float]:
    """Один вектор слота move-plan (порядок = spec3.CELL3_FEATURES, длина = 21).

    ЭТАП 5 (часть 2): позиционный признак slotIndex убран — выводится только slotActive (=1 для
    живого слота). plan-голова не видит, каким по счёту идёт слот, и обязана выбирать по
    содержимому плана; это делает голову инвариантной к перестановке меню (serve/train одно).
    """
    atk, end = plan["attack_cell"], plan["end_cell"]
    origin = ctx.src_cell
    speed = max(1, obs["me"]["speedCells"])
    enemies = [e for e in obs["enemies"] if e["hostile"] and e["alive"]]
    a_gap = min([cell_distance(atk, _enemy_cell(ctx, e)) for e in enemies] or [D])
    o_gap = min([cell_distance(origin, _enemy_cell(ctx, e)) for e in enemies] or [D])
    e_gap = min([cell_distance(end, _enemy_cell(ctx, e)) for e in enemies] or [D])
    sure = any(w["bestModeSure"] and a_gap <= w["sureCells"] + 0.5 for w in obs["weapons"])
    doubt = any(a_gap <= w["doubtCells"] + 0.5 for w in obs["weapons"])
    can = bool(enemies) and doubt
    # угроза в финальной позиции: сколько врагов способны дойти/дотянуться до end_cell
    threat = sum(1 for e in enemies
                 if cell_distance(end, _enemy_cell(ctx, e)) <= e["reachCells"] + e["speedCells"] + 1)
    cover = 1.0 if threat == 0 else 0.0                       # end_cell вне досягаемости ответки
    los = any(has_los(ctx, atk, _enemy_cell(ctx, e), segments) for e in enemies)
    stay = plan["attack_cell"] == origin and plan["end_cell"] == origin
    reloc = plan["attack_cell"] == plan["end_cell"] and plan["attack_cell"] != origin
    return [1.0] + [                                   # slotActive; позиционный индекс убран (ЭТАП 5)
        _r(plan["adx"] / D), _r(plan["ady"] / D), _r(plan["adist"] / D),   # adx, ady, adist
        _r(plan["edx"] / D), _r(plan["edy"] / D), _r(plan["edist"] / D),   # edx, edy, edist
        _r(plan["costIn"] / speed), _r(plan["costOut"] / speed),           # costIn, costOut
        _r(plan["costTotal"] / speed), _r(plan["costTotal"] / speed),      # costTotal, budgetFrac
        1.0 if sure else 0.0, 1.0 if doubt else 0.0, 1.0 if can else 0.0,  # sure/doubt/canAttack
        1.0 if stay else 0.0, 1.0 if reloc else 0.0,                       # stay, pureMove
        1.0 if plan["retreatToOrigin"] else 0.0,                           # retreatToOrigin
        1.0 if e_gap > o_gap + 1e-9 else 0.0,                              # gapIncrease
        cover, _r(threat / max(1, len(enemies))), 1.0 if los else 0.0,     # coverFinal, threatFinal, losAttack
    ]


def cell_vectors_v3(ctx: BattleContext, obs: Dict[str, Any], slots: slots_v3.SlotsV3) -> List[List[float]]:
    """Слоты группы cells = перемещения-планы; досланы пустыми до K_MOVEPLAN+1 (как encode.cell_vectors)."""
    segments = sight_segments(ctx)
    total, size = spec3.K_MOVEPLAN + 1, len(spec3.CELL3_FEATURES)
    vecs = [plan_vector(ctx, obs, p, i, total, segments) for i, p in enumerate(slots.plans[:spec3.K_MOVEPLAN])]
    return enc._group(vecs, total, size)


def observation(ctx: BattleContext, obs: Dict[str, Any], slots: slots_v3.SlotsV3) -> Dict[str, Any]:
    """Векторы состояния и слотов без разметки (схема 3): те же ключи, что у encode.observation."""
    return {
        "schema": spec3.SCHEMA, "state": enc.state(obs),
        "cells": cell_vectors_v3(ctx, obs, slots),
        "targets": enc.target_vectors(obs, slots),
        "weapons": enc.weapon_vectors(obs, slots),
        "mask": {"cells": enc._mask(slots.n_plans, spec3.K_MOVEPLAN + 1, False),
                 "targets": enc._mask(len(slots.targets), spec.K_TARGETS + 1, True),
                 "weapons": enc._mask(len(slots.weapons), spec.K_WEAPONS + 1, True)},
    }


def encode(ctx: BattleContext, obs: Dict[str, Any], slots: slots_v3.SlotsV3,
           label: Dict[str, int], value: float = 0.0, meta: Dict[str, Any] = None) -> Dict[str, Any]:
    """Один пример выборки схемы 3: наблюдение + метка {plan,target,weapon} + значение учителя.

    Mirror of encode.encode: добавляем точную совместную маску legal = joint.legal_mask(slots,
    ctx, schema=3) там, где живы ctx/slots (serving-путь observation её не получает).
    """
    sample = observation(ctx, obs, slots)
    sample["feat_version"] = spec3.FEATURES_VERSION      # явная версия признаков v3 (ЭТАП 6, 1.2)
    sample["legal"] = joint.legal_mask(slots, ctx, spec3.SCHEMA)
    sample["y"] = {"plan": label["plan"], "target": label["target"], "weapon": label["weapon"]}
    sample["value"] = _r(max(-3.0, min(3.0, value / spec.VALUE_SCALE)))
    sample["meta"] = dict(meta or {}, schema=spec3.SCHEMA, src=ctx.src_id, cell=list(ctx.src_cell))
    return sample
