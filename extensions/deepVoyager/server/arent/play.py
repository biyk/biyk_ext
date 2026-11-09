# arent/play.py — модель -> список действий формата /plan.
#
# Тот же конвейер, что при генерации выборки: payload -> наблюдение -> слоты ->
# векторы -> три индекса -> slots.decode. Схемы 3: конечная тройка выбирается ОБЩИМ
# joint-декодером (arent/joint.py: максимум совместной вероятности по A(s)), поэтому
# действие политики всегда легально и защитный legalize — тождество; независимый argmax
# голов остаётся только диагностическим baseline (y_proposed). Схема 2 декодируется тем же
# joint-декодером (Этап 7 завершён: serving==train по множеству A(s)).
# Поэтому ответ модели устроен точно как
# ответ планировщика, и Foundry его принимает без особых доработок: цель, шаги, атака.
# Ни lookahead, ни таймеров здесь нет — один прямой проход сети.
import json
import math
import os
from typing import Any, Callable, Dict, List, Optional

from arent import backend, encode, encode_v3, encode_v4, encode_v5, joint as joint_mod, \
    legalize as legalize_mod, net, paths, slots as slots_mod, slots_v3, spec, spec3, spec4, spec5
from arent.net import GROUPS, GROUPS_V5, Y_KEY, groups_for
from arent.observe import observe
from planner.context import BattleContext


def _schema_of(model) -> int:
    """Версия задачи модели (2 = клетка, 3 = move-plan); старые веса без cfg -> 2."""
    return int(getattr(getattr(model, "cfg", None), "schema", spec.SCHEMA))


def _attack_view(raw: Dict[str, int], label: Dict[str, int], reason, slots: Any) -> Dict[str, Any]:
    """Диагностика легальности хода: что предложил БАЗОВЫЙ независимый argmax, что исполнила
    политика (joint-декодер), и изменил ли защитный legalize joint-выбор (не должен).
    """
    nt, nw = len(slots.targets), len(slots.weapons)
    proposed = 0 <= raw.get("target", -1) < nt and 0 <= raw.get("weapon", -1) < nw
    executed = 0 <= label.get("target", -1) < nt and 0 <= label.get("weapon", -1) < nw
    return {"proposed": proposed, "executed": executed,
            "corrected": bool(reason), "illegal_proposal": proposed and not executed,
            "reason": reason}


def _head_probs(logps: Dict[str, List[float]], label: Dict[str, int], yk: Dict[str, str],
                groups: tuple) -> Dict[str, float]:
    """Вероятности голов для ВЫБРАННОЙ тройки (не для baseline-предложения)."""
    out = {}
    for group in groups:
        key = yk[group]
        idx = int(label.get(key, -1))
        vec = logps[group]
        out[key] = round(math.exp(vec[idx]), 4) if 0 <= idx < len(vec) else 0.0
    return out


def act(model: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Один ход модели: (клетка/план, цель, оружие) -> действия + разбор «что выбрано».

    Схема берётся из cfg модели, поэтому v3-чекпойнт декодируется через move-plan-слоты
    (атака из attack_cell, затем отступление), а v2 — по-прежнему через клетки. Контракт
    ответа (/plan-потребитель читает result["actions"]) одинаков в обеих схемах.
    """
    ctx = BattleContext.from_payload(payload)
    obs = observe(ctx)
    schema = _schema_of(model)
    yk = net.y_key(schema)

    if schema >= spec5.SCHEMA:                            # v5: move-plan + economy + maneuver head
        slots = slots_v3.build(ctx, obs)
        # populate maneuver slots from payload
        maneuver_items = payload.get("maneuvers", [])
        slots.maneuvers = list(maneuver_items)
        sample = encode_v5.observation(ctx, obs, slots)
        out = model.predict(sample)                       # diagnostic baseline (independent argmax)
        dec = joint_mod.decode_v5(model, sample, slots, ctx, schema)
        label = dec["label"]
        actions = slots_v3.decode_v5(slots, label)
        return {
            "schema": schema, "actions": [a.to_dict() for a in actions], "y": label,
            "y_proposed": {yk[g]: out[yk[g]] for g in groups_for(schema) if g in yk},
            "decoder": "joint_argmax_v5",
            "joint": {"prob": dec["joint_prob"]},
            "value": dec["value"],
            "prob": _head_probs(dec["logp"], label, yk, tuple(groups_for(schema))),
            "names": {"cell": _plan(slots, label.get("plan", -1)),
                      "target": _name(slots.targets, label.get("target", -1)),
                      "weapon": _name(slots.weapons, label.get("weapon", -1)),
                      "maneuver": _name(slots.maneuvers, label.get("maneuver", -1))},
            "counts": {"cells": slots.n_plans, "targets": len(slots.targets),
                       "weapons": len(slots.weapons), "maneuvers": len(slots.maneuvers)},
            "me": obs["me"]["name"], "src": ctx.src_id, "grid": obs["grid"],
        }

    if spec3.uses_moveplan(schema):                # v3/v4: голова move-plan (атака+отступление)
        slots = slots_v3.build(ctx, obs)
        sample = (encode_v4.observation(ctx, obs, slots) if schema == spec4.SCHEMA
                  else encode_v3.observation(ctx, obs, slots))
        out = model.predict(sample)                # диагностический baseline: независимый argmax
        raw = {yk[group]: out[yk[group]] for group in GROUPS}
        dec = joint_mod.decode(model, sample, slots, ctx, schema)
        # защитный legalize: для joint-выбора обязан быть тождеством; расхождение — нарушение
        # контракта (диагностическая ошибка), а не штатная починка действия
        label, reason = legalize_mod.legalize(dec["label"], schema, slots, ctx)
        violation = bool(reason) or dict(label) != dict(dec["label"])
        actions = slots_v3.decode(slots, label)
        return {
            "schema": schema, "actions": [a.to_dict() for a in actions], "y": label,
            "y_proposed": raw, "decoder": "joint_argmax", "legalize": _attack_view(raw, label, reason, slots),
            "joint": {"prob": dec["joint_prob"], "violation": violation},
            "value": dec["value"],
            "prob": _head_probs(dec["logp"], label, yk, GROUPS),
            "names": {"cell": _plan(slots, label["plan"]),
                      "target": _name(slots.targets, label["target"]),
                      "weapon": _name(slots.weapons, label["weapon"])},
            "counts": {"cells": slots.n_plans, "targets": len(slots.targets),
                       "weapons": len(slots.weapons)},
            "me": obs["me"]["name"], "src": ctx.src_id, "grid": obs["grid"],
        }
    slots = slots_mod.build(ctx, obs)
    sample = encode.observation(ctx, obs, slots)
    out = model.predict(sample)                # диагностический baseline: независимый argmax
    raw = {Y_KEY[group]: out[Y_KEY[group]] for group in GROUPS}
    # схема 2 переведена на тот же joint-декодер, что и обучение (BC joint NLL / PPO берут
    # logπ по A(s)): выбор политики уже совместен, protective legalize — тождество.
    dec = joint_mod.decode(model, sample, slots, ctx, schema)
    label, reason = legalize_mod.legalize(dec["label"], schema, slots, ctx)
    violation = bool(reason) or dict(label) != dict(dec["label"])
    actions = slots_mod.decode(slots, label)
    return {
        "schema": schema, "actions": [a.to_dict() for a in actions], "y": label, "value": out["value"],
        "y_proposed": raw, "decoder": "joint_argmax", "legalize": _attack_view(raw, label, reason, slots),
        "joint": {"prob": dec["joint_prob"], "violation": violation},
        "prob": _head_probs(dec["logp"], label, Y_KEY, GROUPS),
        "names": {"cell": _cell(slots, label["cell"]), "target": _name(slots.targets, label["target"]),
                  "weapon": _name(slots.weapons, label["weapon"])},
        "counts": {"cells": len(slots.cells), "targets": len(slots.targets),
                   "weapons": len(slots.weapons)},
        "me": obs["me"]["name"], "src": ctx.src_id, "grid": obs["grid"],
    }


def _name(entries: list, index: int) -> Optional[str]:
    return entries[index]["name"] if 0 <= index < len(entries) else None


def _cell(slots: Any, index: int) -> str:
    """Как модель объяснила свой ход: стоять или маршрут направлениями."""
    if not 0 <= index < len(slots.cells):
        return "нет клетки"
    dirs = slots.cells[index]["dirs"]
    return "стоять" if not dirs else "->".join(dirs)


def _plan(slots: Any, index: int) -> str:
    """Разбор move-plan'а (схема 3): подход к позиции удара и, если есть, отступление."""
    if not 0 <= index < getattr(slots, "n_plans", 0):
        return "нет плана"
    plan = slots.plans[index]
    inward = "->".join(plan["dirs_in"]) or "стоять"
    outward = "->".join(plan["dirs_out"])
    return inward if not outward else f"{inward} | уход {outward}"


def read_payload(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run(model_path: Optional[str] = None, payload: Optional[Dict[str, Any]] = None,
        payload_path: Optional[str] = None, arena: Optional[str] = None,
        out: Optional[str] = None, kind: str = "auto",
        log: Optional[Callable] = None) -> Dict[str, Any]:
    """Сыграть моделью по снимку сцены: --model + один из (payload|файл|имя арены)."""
    say = log or (lambda *a: print(*a, flush=True))
    model_path = _checkpoint_path(model_path) or latest_checkpoint()
    if not model_path:
        raise RuntimeError("Чекпойнта нет: сначала arent train")
    data = payload
    if data is None and payload_path:
        data = read_payload(payload_path)
    if data is None and arena:
        from playground import arena as arena_module
        data = arena_module.load_arena(arena)
    if data is None:
        raise RuntimeError("Нужен снимок сцены: --payload или --arena")
    result = act(backend.load_policy(model_path, kind=kind), data)
    say(json.dumps({"ход": result["me"], "действия": result["actions"],
                    "выбор": result["names"], "ценность": result["value"],
                    "вероятности": result["prob"]}, ensure_ascii=False, indent=1))
    if out:
        parent = os.path.dirname(os.path.abspath(out))
        os.makedirs(parent, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
    return result


def _checkpoint_path(model_path: Optional[str]) -> Optional[str]:
    """--model принимает и путь к model.json, и имя прогона (runs/<имя>/model.json)."""
    if not model_path:
        return None
    if os.path.exists(model_path):
        return model_path
    return latest_checkpoint(model_path)


def latest_checkpoint(name: Optional[str] = None) -> Optional[str]:
    """runs/<имя>/model.json: по имени прогона или самый свежий из лежащих в runs/."""
    if name:
        return paths.checkpoint(name)
    root = paths.runs_dir()
    if not os.path.isdir(root):
        return None
    if name:
        direct = paths.file_in(paths.file_in(root, name), "model.json")
        return direct if os.path.exists(direct) else None
    found = [os.path.join(root, run_name, "model.json") for run_name in os.listdir(root)
             if os.path.exists(os.path.join(root, run_name, "model.json"))]
    return max(found, key=os.path.getmtime) if found else None
