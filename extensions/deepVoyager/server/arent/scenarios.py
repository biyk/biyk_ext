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
import json
import os
import random
from typing import Any, Dict, List, Optional, Tuple

from arent import scenario_layout as sl
from arent.scenario_units import (
    ARCHETYPES, ARSENAL_NAMES, CLASS_NAMES, HERO_ARSENALS, TACTICAL,
    UNIT_CLASSES, make_unit, mirror_size, stats,
)
from playground import arena

GEN_PREFIX = "gen_"


def _token(unit: Dict[str, Any], cell) -> Dict[str, Any]:
    """Юнит + клетка -> запись арены: равные права сторон, у каждого своё оружие."""
    return {"id": unit["id"], "name": unit["name"], "disposition": unit["disposition"],
            "cell": list(cell), "hp": unit["hp"], "speed": unit["speed"],
            "damage": unit["damage"], "reachFt": unit["reachFt"],
            "hitChance": unit["hitChance"], "initiative": unit["initiative"],
            "weapons": unit["weapons"]}

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
    n_side = mirror_size(rng)                           # зеркальный состав: n на n

    def pick_arsenal() -> str:
        name = rng.choice(ARSENAL_NAMES)
        if arch in ("line", "cover") and rng.random() < 0.5:   # зеркально обеим сторонам
            name = rng.choice(["bow", "mixed", "javelins"])
        return name

    side_a = [make_unit(rng.choice(CLASS_NAMES), rng, i + 1, -1, "A", pick_arsenal())
              for i in range(n_side)]
    side_b = [make_unit(rng.choice(spec["classes"]), rng, i + 1, 1, "F", pick_arsenal())
              for i in range(n_side)]

    mode = spec["deploy"] if not do_random else rng.choice(sl.DEPLOYMENTS)
    jitter = 2 if do_random else 0
    formation = sl.FORMATIONS[spec["formation"]]
    a_cells, b_cells, used_mode = sl.place(
        rng, rows, cols, n_side, formation, n_side, formation, mode, jitter)

    tokens: List[Dict[str, Any]] = []
    for unit, cell in zip(side_a + side_b, list(a_cells) + list(b_cells)):
        tokens.append(_token(unit, cell))

    raw = {
        "comment": f"gen arch={arch} side_a={n_side} side_b={n_side} field={field_profile} "
                   f"walls={wall_profile} deploy={used_mode} "
                   f"layout={'random' if do_random else 'structured'}",
        "scene": {"width": cols * sl.GRID, "height": rows * sl.GRID, "gridSize": sl.GRID},
        "target": side_b[0]["id"] if side_b else None,
        "walls": sl.build_walls(rng, wall_profile, rows, cols),
        "tokens": tokens,
    }
    name = f"{GEN_PREFIX}{arch}_{seq:03d}"
    params = {
        "seed": seed, "seq": seq, "group_id": name, "archetype": arch,
        "field": [rows, cols], "field_profile": field_profile,
        "wall_profile": wall_profile, "n_walls": len(raw["walls"]),
        "deployment": used_mode, "layout": "random" if do_random else "structured",
        # n_allies/n_foes сохранены как имена-стажы (split/тесты), но теперь sides равны
        "n_allies": n_side, "n_foes": n_side,
        "side_a_classes": [u["_class"] for u in side_a], "side_b_classes": [u["_class"] for u in side_b],
        "side_a_arsenals": [u["arsenal"] for u in side_a], "side_b_arsenals": [u["arsenal"] for u in side_b],
        "side_a_stats": [stats(u) for u in side_a], "side_b_stats": [stats(u) for u in side_b],
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
