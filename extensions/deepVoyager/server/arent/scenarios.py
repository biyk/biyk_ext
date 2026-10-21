# arent/scenarios.py — сборка НЕЗАВИСИМЫХ боевых сценариев из seed (структурное разнообразие).
#
# Почему отдельный генератор, а не states.variants: variants меняет лишь кто ходит и куда
# сдвинулись фигуры после случайных раундов — СОСТАВ (число/классы юнитов, оружие капитана,
# стены, рисунок) остаётся ровно тем, что в файле арены. Значит разные seed внутри одной
# арены — НЕ новые сценарии, а возмущение одного. Здесь же сцена собирается заново по осям:
#   • тактический архетип (построение) + профиль поля + профиль стен (стены НЕ из архетипа);
#   • симметричные составы 1..6 своих vs 1..6 врагов из ОБЩЕГО пула ролей и вооружения;
#   • расстановка: две зоны deployment + джиттер ±2 (random) против канона без джиттера
#     (structured) — канон держим для тактических архетипов, чтобы A/B «политика vs учитель»
#     шёл на идентичном старте.
# Реестр ролей/архетипов/арсеналов — в scenario_units.py, геометрия — в scenario_layout.py.
# ho_*/ho2_* (замороженные независимые наборы) не производятся и не перезаписываются.
import copy
import json
import os
import random
from typing import Any, Dict, List, Optional, Tuple

from arent import scenario_layout as sl
from arent.scenario_units import (
    ARCHETYPES, ARSENAL_NAMES, CLASS_NAMES, HERO_ARSENALS, TACTICAL,
    UNIT_CLASSES, make_unit, stats, team_sizes,
)
from playground import arena

GEN_PREFIX = "gen_"

# Реэкспорт реестра: прежние потребители (тесты, abset) обращаются через scenarios.*.
__all__ = ["ARCHETYPES", "HERO_ARSENALS", "TACTICAL", "UNIT_CLASSES",
           "build", "build_valid", "generate", "write_arenas", "_bc"]


def _bc(payload: Dict[str, Any]):
    from planner.context import BattleContext
    return BattleContext.from_payload(payload)


def build(seq: int, seed: int, random_start: Optional[bool] = None
          ) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """(имя, arena-raw, params) — один независимый сценарий из детерминированного семени.

    random_start: True — зоны+джиттер всем; False — каноническая геометрия; None — по
    архетипу (тактические -> канон, остальные -> рандом). Один seed => идентичный сценарий:
    учитель и политика видят ровно одну и ту же расстановку.
    """
    rng = random.Random((seed * 100003) ^ (seq * 7919))
    arch = rng.choice(sorted(ARCHETYPES))
    spec = ARCHETYPES[arch]
    do_random = (arch not in TACTICAL) if random_start is None else bool(random_start)

    field_profile, rows, cols = sl.pick_field(rng)
    wall_profile = sl.pick_wall_profile(rng)
    n_ours, n_foes = team_sizes(rng)

    foes = [make_unit(rng.choice(spec["classes"]), rng, i + 1, 1, "F") for i in range(n_foes)]
    allies = [make_unit(rng.choice(CLASS_NAMES), rng, i + 1, -1, "AL") for i in range(n_ours - 1)]
    ally_arsenals = [rng.choice(ARSENAL_NAMES) for _ in allies]

    cap_cls = rng.choice(CLASS_NAMES)
    hero_hp = rng.choice([18, 24, 30, 36, 45])
    arsenal_name = rng.choice(ARSENAL_NAMES)
    if arch in ("line", "cover") and rng.random() < 0.5:      # против линии чаще дать ответный огонь
        arsenal_name = rng.choice(["bow", "mixed", "javelins"])
    weapons = copy.deepcopy(HERO_ARSENALS[arsenal_name])

    mode = spec["deploy"] if not do_random else rng.choice(sl.DEPLOYMENTS)
    jitter = 2 if do_random else 0
    our_cells, foe_cells, used_mode = sl.place(
        rng, rows, cols, n_ours, sl.CLUSTER, n_foes, sl.FORMATIONS[spec["formation"]], mode, jitter)

    tokens: List[Dict[str, Any]] = [
        {"id": "A", "name": "Капитан", "disposition": -1, "cell": list(our_cells[0]), "hp": hero_hp}]
    for ally, (r, c) in zip(allies, our_cells[1:]):
        tokens.append({"id": ally["id"], "name": ally["name"], "disposition": -1, "cell": [r, c],
                       "hp": ally["hp"], "speed": ally["speed"], "damage": ally["damage"],
                       "reachFt": ally["reachFt"], "hitChance": ally["hitChance"]})
    for foe, (r, c) in zip(foes, foe_cells):
        tokens.append({"id": foe["id"], "name": foe["name"], "disposition": 1, "cell": [r, c],
                       "hp": foe["hp"], "speed": foe["speed"], "damage": foe["damage"],
                       "reachFt": foe["reachFt"], "hitChance": foe["hitChance"]})

    raw = {
        "comment": f"gen arch={arch} ours={n_ours} foes={n_foes} field={field_profile} "
                   f"walls={wall_profile} deploy={used_mode} "
                   f"layout={'random' if do_random else 'structured'}",
        "scene": {"width": cols * sl.GRID, "height": rows * sl.GRID, "gridSize": sl.GRID},
        "target": foes[0]["id"] if foes else None,
        "walls": sl.build_walls(rng, wall_profile, rows, cols),
        "tokens": tokens,
        "hero": {"id": "A", "speed": rng.choice([30, 30, 30, 40]), "weapons": weapons},
    }
    name = f"{GEN_PREFIX}{arch}_{seq:03d}"
    params = {
        "seed": seed, "seq": seq, "group_id": name, "archetype": arch,
        "field": [rows, cols], "field_profile": field_profile,
        "wall_profile": wall_profile, "n_walls": len(raw["walls"]),
        "deployment": used_mode, "layout": "random" if do_random else "structured",
        "n_allies": n_ours, "n_foes": n_foes,
        "hero_class": cap_cls, "arsenal": arsenal_name, "hero_hp": hero_hp,
        "ally_classes": [a["_class"] for a in allies], "ally_arsenals": ally_arsenals,
        "ally_stats": [stats(a) for a in allies],
        "foe_classes": [f["_class"] for f in foes], "foe_stats": [stats(f) for f in foes],
    }
    return name, raw, params


def build_valid(seq: int, seed: int, tries: int = 6, random_start: Optional[bool] = None
                ) -> Optional[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """build + проверка валидности боя; при неудаче сдвигает под-семя (в пределах seed)."""
    for k in range(tries):
        name, raw, params = build(seq * 16 + k, seed, random_start)
        try:
            payload = arena.build_payload(raw, name)
            ctx = _bc(payload)
            if ctx.hostile_targets() and ctx.src.is_alive and payload.get("weapons"):
                return name, raw, params
        except Exception:
            continue
    return None


def generate(count: int, seed: int, random_start: Optional[bool] = None
             ) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """count валидных независимых сценариев; имена уникальны, ho_*/ho2_* не производятся."""
    out: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    seen = set()
    seq = 0
    while len(out) < count and seq < count * 4:
        built = build_valid(seq, seed, random_start=random_start)
        seq += 1
        if built and built[0] not in seen:
            seen.add(built[0])
            out.append(built)
    return out


def _reserved(name: str) -> bool:
    return name.startswith("ho_") or name.startswith("ho2_")


def write_arenas(scenarios: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
                 out_dir: Optional[str] = None, manifest: Optional[str] = None) -> Dict[str, Any]:
    """Пишет arena-файлы (по умолчанию в playground/arenas) + манифест seed/params/group.

    ho_*/ho2_* не перезаписываются (замороженный набор неприкосновенен): такие имена
    отфильтрованы, даже если их подсунуть явно. Манифест — единый источник истины о
    происхождении каждого сценария (для честного train/val split по группам).
    """
    directory = out_dir or arena.ARENAS_DIR
    os.makedirs(directory, exist_ok=True)
    records = []
    for name, raw, params in scenarios:
        if _reserved(name):
            continue
        with open(os.path.join(directory, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=1)
        records.append({"name": name, "group_id": params["group_id"], "seed": params["seed"],
                        "archetype": params["archetype"], "params": params})
    if manifest:
        os.makedirs(os.path.dirname(manifest), exist_ok=True)
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump({"base_seed": (records[0]["seed"] if records else None),
                       "count": len(records), "scenarios": records},
                      f, ensure_ascii=False, indent=1)
    return {"written": len(records), "dir": directory, "manifest": manifest}
