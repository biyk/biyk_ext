# arent/play.py — модель -> список действий формата /plan.
#
# Тот же конвейер, что при генерации выборки: payload -> наблюдение -> слоты ->
# векторы -> три индекса -> slots.decode. Поэтому ответ модели устроен точно как
# ответ планировщика, и Foundry его принимает без особых доработок: цель, шаги, атака.
# Ни lookahead, ни таймеров здесь нет — один прямой проход сети.
import json
import os
from typing import Any, Callable, Dict, Optional

from arent import backend, encode, paths, slots as slots_mod
from arent.net import GROUPS, Y_KEY
from arent.observe import observe
from planner.context import BattleContext


def act(model: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Один ход модели: (клетка, цель, оружие) -> действия + разбор «что выбрано»."""
    ctx = BattleContext.from_payload(payload)
    obs = observe(ctx)
    slots = slots_mod.build(ctx, obs)
    out = model.predict(encode.observation(ctx, obs, slots))
    label = {Y_KEY[group]: out[Y_KEY[group]] for group in GROUPS}
    actions = slots_mod.decode(slots, label)
    return {
        "actions": [a.to_dict() for a in actions], "y": label, "value": out["value"],
        "prob": {Y_KEY[group]: out[Y_KEY[group] + "Prob"] for group in GROUPS},
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
