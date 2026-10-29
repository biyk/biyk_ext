# arent/encode_v4.py — наблюдение схемы 4: как v3 (move-plan), но с экномикой действий и Ao.
#
# Перенос весов v3->v4 тривиален, потому что новые признаки добавляются ТОЛЬКО В ХВОСТ блоков:
#   state   = encode.state (старые колонки на местах) + resource_tail (после grid);
#   cells   = encode_v3.plan_vector (CELL3) + [provokesAo, aoRisk]         (в конец слота);
#   weapons = encode.weapon_slot (WEAPON_FEATURES) + [isAction,isBonus,isReaction] (в конец head-слота).
# Блок оружия ВНУТРИ global-state остаётся СТАРОЙ ширины (spec.WEAPON_FEATURES): активация живёт
# только в head оружия, иначе сдвинулся бы grid и разрушился побитовый перенос trunk1.
#
# provokesAo/aoRisk — ГЕЙТ-признак для модели (правду enforce-ит sim.apply_actor_seq(reactions=True)):
# идёт ли план через границу melee-зоны живого врага с неподрашённой реакцией (выход = Ao) и каков
# ожидаемый урон от такого Ao. Семантика действия/тройки/меню — как v3 (uses_moveplan), поэтому
# decode/legal_mask/attackable_v3 общие; меняются лишь ширина признаков и ключ схемы.
from typing import Any, Dict, List, Tuple

from planner.context import BattleContext
from planner.geometry import apply_moves, cell_distance
from arent import encode as enc
from arent import encode_v3 as enc3
from arent import joint, spec, spec3, spec4, slots_v3
from arent.observe import has_los, sight_segments

D = spec.D_SCALE
_r = enc._r
_ZONE_TOL = 1e-6


def resource_tail(obs: Dict[str, Any]) -> List[float]:
    """Хвост state: сколько ресурсов хода осталось у актёра (action/bonus/reaction remaining).

    observe проставил me.*Remaining (по умолчанию 1 — всё доступно). Здесь только нормировка 0/1.
    Порядок = spec4.RESOURCE_FEATURES. Старые колонки state (me|enemies|allies|weapons|grid) не
    трогаются: хвост добавляется ПОСЛЕ grid, поэтому trunk1 переносится copy[:, :old]+pad.
    """
    me = obs.get("me", {})
    return [_r(float(me.get(k, 1.0))) for k in spec4.RESOURCE_FEATURES]


def state(obs: Dict[str, Any]) -> List[float]:
    """Вектор состояния v4 = v2/v3-состояние + хвост ресурсов (ширина dims4()['state'])."""
    return enc.state(obs) + resource_tail(obs)


def weapon_slot_v4(w: Dict[str, Any], index: int, total: int) -> List[float]:
    """Head-слот оружия v4 = старый weapon_slot (WEAPON_FEATURES) + флаги активации в конец.

    isAction: любая атака тратит действие -> 1 для боевого слота; isReaction: ближний бой (не
    ranged/thrown) может ответить Ao; isBonus: бонус-атак пока не моделируем -> 0. Влияет только
    на head оружия (state-блок оружия остаётся старой ширины через enc.weapon_slot).
    """
    if not w:
        return enc._empty(len(spec4.WEAPON_FEATURES4), index, total)
    base = enc.weapon_slot(w, index, total)              # 11 колонок (порядок = spec.WEAPON_FEATURES)
    melee = not w.get("ranged") and not w.get("thrown")
    return base + [1.0, 0.0, 1.0 if melee else 0.0]      # isAction, isBonus, isReaction


def weapon_vectors(obs: Dict[str, Any], slots: Any) -> List[List[float]]:
    """Слоты оружия фиксированной ширины WEAPON_FEATURES4 + «не атаковать» последним."""
    total = spec.K_WEAPONS + 1
    return enc._group([weapon_slot_v4(w, i, total) for i, w in enumerate(slots.weapons)],
                      total, len(spec4.WEAPON_FEATURES4))


def _ao_exposure(ctx: BattleContext, obs: Dict[str, Any], plan: Dict[str, Any],
                 segments) -> Tuple[bool, float]:
    """Провоцирует ли план Ao и каков ожидаемый урон: обход по hops пути origin->dirs_in->dirs_out.

    Ao = выход (prev в melee-зоне, cur вне) через границу зоны живого врага с неподрашённой реакцией
    (reactionRemaining>=1) и чистой LOS. Каждый враг бьёт не более одного Ao (реакция списывается).
    Это ПРИЗНАК для модели; точный урон/списание считает sim (apply_actor_seq reactions=True)."""
    origin = ctx.src_cell
    path, cell = [origin], origin
    for d in plan["dirs_in"]:
        cell = apply_moves(cell, [d])
        path.append(cell)
    for d in plan["dirs_out"]:
        cell = apply_moves(cell, [d])
        path.append(cell)
    armed = [e for e in obs["enemies"]
             if e["hostile"] and e["alive"] and float(e.get("reactionRemaining", 1.0)) >= 1.0]
    hit, risk, struck = False, 0.0, set()
    for prev, cur in zip(path, path[1:]):
        for e in armed:
            if e["id"] in struck:
                continue
            ec = enc3._enemy_cell(ctx, e)
            reach = float(e["reachCells"]) + _ZONE_TOL
            was_in = cell_distance(ec, prev) <= reach and has_los(ctx, ec, prev, segments)
            now_out = not (cell_distance(ec, cur) <= reach and has_los(ctx, ec, cur, segments))
            if was_in and now_out:
                hit = True
                struck.add(e["id"])
                risk += float(e.get("dmgToMe", 0.0))
    return hit, risk


def plan_vector_v4(ctx: BattleContext, obs: Dict[str, Any], plan: Dict[str, Any],
                   index: int, total: int, segments) -> List[float]:
    """Один слот move-plan v4: вектор v3 (CELL3_FEATURES, 21) + [provokesAo, aoRisk] (в конец)."""
    provokes, risk = _ao_exposure(ctx, obs, plan, segments)
    return enc3.plan_vector(ctx, obs, plan, index, total, segments) + [
        1.0 if provokes else 0.0, _r(risk / spec.DMG_SCALE)]


def cell_vectors_v4(ctx: BattleContext, obs: Dict[str, Any], slots: slots_v3.SlotsV3) -> List[List[float]]:
    """Слоты cells = move-plan'ы v4 (ширина CELL4_FEATURES), досланы пустыми до K_MOVEPLAN+1."""
    segments = sight_segments(ctx)
    total, size = spec3.K_MOVEPLAN + 1, len(spec4.CELL4_FEATURES)
    vecs = [plan_vector_v4(ctx, obs, p, i, total, segments) for i, p in enumerate(slots.plans[:spec3.K_MOVEPLAN])]
    return enc._group(vecs, total, size)


def observation(ctx: BattleContext, obs: Dict[str, Any], slots: slots_v3.SlotsV3) -> Dict[str, Any]:
    """Векторы состояния/слотов v4 без разметки: те же ключи, что у encode_v3.observation."""
    return {
        "schema": spec4.SCHEMA, "state": state(obs),
        "cells": cell_vectors_v4(ctx, obs, slots),
        "targets": enc.target_vectors(obs, slots),
        "weapons": weapon_vectors(obs, slots),
        "mask": {"cells": enc._mask(slots.n_plans, spec3.K_MOVEPLAN + 1, False),
                 "targets": enc._mask(len(slots.targets), spec.K_TARGETS + 1, True),
                 "weapons": enc._mask(len(slots.weapons), spec.K_WEAPONS + 1, True)},
    }


def encode(ctx: BattleContext, obs: Dict[str, Any], slots: slots_v3.SlotsV3,
           label: Dict[str, int], value: float = 0.0, meta: Dict[str, Any] = None) -> Dict[str, Any]:
    """Один пример выборки схемы 4: наблюдение + метка {plan,target,weapon} + значение учителя."""
    sample = observation(ctx, obs, slots)
    sample["feat_version"] = spec4.FEATURES_VERSION
    sample["legal"] = joint.legal_mask(slots, ctx, spec4.SCHEMA)
    sample["y"] = {"plan": label["plan"], "target": label["target"], "weapon": label["weapon"]}
    sample["value"] = _r(max(-3.0, min(3.0, value / spec.VALUE_SCALE)))
    sample["meta"] = dict(meta or {}, schema=spec4.SCHEMA, src=ctx.src_id, cell=list(ctx.src_cell))
    return sample
