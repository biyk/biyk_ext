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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from arent import scenario_layout as sl
from arent.tactics_geom import chokepoint_cells
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


def _mirror_of(a: Dict[str, Any], n: int) -> Dict[str, Any]:
    """Точная копия юнита A как сторона F: те же hp/speed/damage/reach/hitChance/initiative/оружие.

    Настоящее зеркало (Этап 2): различаются лишь id/имя/disposition — состав и силы равны,
    поэтому исход дуэли решает тактика и очерёдность, а не удача в броске статов.
    """
    b = copy.deepcopy(a)
    b["id"] = f"F{n}"
    b["name"] = f"{a['_class']}-{n}"
    b["disposition"] = 1
    return b

# Реэкспорт реестра: прежние потребители (тесты, abset) обращаются через scenarios.*.
__all__ = ["ARCHETYPES", "HERO_ARSENALS", "STAGE2_DUEL_PROFILES", "STAGE3_PAIRS", "TACTICAL",
           "UNIT_CLASSES", "build", "build_valid", "generate", "generate_duels",
           "generate_mirror_duels", "generate_asym_duels", "generate_stage3_pool",
           "write_arenas", "_bc"]


def _bc(payload: Dict[str, Any]):
    from planner.context import BattleContext
    return BattleContext.from_payload(payload)


def build(seq: int, seed: int, random_start: Optional[bool] = None, *,
          archetype: Optional[str] = None, classes: Optional[Sequence[str]] = None,
          foe_classes: Optional[Sequence[str]] = None, arsenals: Optional[Sequence[str]] = None,
          foe_arsenals: Optional[Sequence[str]] = None, n_side: Optional[int] = None,
          wall_profile: Optional[str] = None, field_profile: Optional[str] = None,
          mirror: bool = False) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """(имя, arena-raw, params) — один независимый сценарий из детерминированного семени.

    random_start: True — зоны+джиттер всем; False — каноническая геометрия; None — по
    архетипу (тактические -> канон, остальные -> рандом). Один seed => идентичный сценарий:
    учитель и политика видят ровно одну и ту же расстановку.

    keyword-only overrides (фильтр арен для curriculum-этапов, teaching_plan §Этап 1): заданная
    ось фиксируется вместо броска rng — archetype/classes (на обе стороны)/arsenals/n_side/
    wall_profile/field_profile. Остальные оси (hp/speed/инициативы) остаются детерминированы
    seed'ом, поэтому разные seq дают разные бои при той же STRUCTURE.
    """
    rng = random.Random((seed * 100003) ^ (seq * 7919))
    arch = archetype or rng.choice(sorted(ARCHETYPES))
    spec = ARCHETYPES[arch]
    do_random = (arch not in TACTICAL) if random_start is None else bool(random_start)

    if field_profile:
        field_profile, rows, cols = sl.pick_field_named(rng, field_profile)
    else:
        field_profile, rows, cols = sl.pick_field(rng)
    wall_profile = wall_profile or sl.pick_wall_profile(rng)
    n_side = n_side or mirror_size(rng)                 # зеркальный состав: n на n

    our_classes = list(classes) if classes else list(CLASS_NAMES)
    if foe_classes:                       # асимметрия этапа 2: сторона B может быть другого класса
        foe_classes = list(foe_classes)
    elif classes:
        foe_classes = list(classes)
    else:
        foe_classes = list(spec["classes"])

    def pick_arsenal(pool: Optional[Sequence[str]]) -> str:
        if pool:
            return rng.choice(list(pool))
        name = rng.choice(ARSENAL_NAMES)
        if arch in ("line", "cover") and rng.random() < 0.5:   # зеркально обеим сторонам
            name = rng.choice(["bow", "mixed", "javelins"])
        return name

    foe_arsenal_pool = foe_arsenals or arsenals

    side_a = [make_unit(rng.choice(our_classes), rng, i + 1, -1, "A", pick_arsenal(arsenals))
              for i in range(n_side)]
    if mirror:                         # настоящее зеркало: B = копия A (равные силы и оружие)
        side_b = [_mirror_of(a, i + 1) for i, a in enumerate(side_a)]
    else:
        side_b = [make_unit(rng.choice(foe_classes), rng, i + 1, 1, "F", pick_arsenal(foe_arsenal_pool))
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
        # has_choke уточняется в build_valid (нужен ctx); здесь честный placeholder по профилю стен.
        "has_choke": wall_profile in ("corridor", "ring", "maze_lite"),
        "deployment": used_mode, "layout": "random" if do_random else "structured",
        # n_allies/n_foes сохранены как имена-стажы (split/тесты), но теперь sides равны
        "n_allies": n_side, "n_foes": n_side,
        "side_a_classes": [u["_class"] for u in side_a], "side_b_classes": [u["_class"] for u in side_b],
        "side_a_arsenals": [u["arsenal"] for u in side_a], "side_b_arsenals": [u["arsenal"] for u in side_b],
        "side_a_stats": [stats(u) for u in side_a], "side_b_stats": [stats(u) for u in side_b],
    }
    return name, raw, params


def build_valid(seq: int, seed: int, tries: int = 6, random_start: Optional[bool] = None,
                **filters) -> Optional[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """build + проверка валидности боя; при неудаче сдвигает под-семя (в пределах seed).

    filters — keyword-only overrides build'а (фильтр арен), пробрасываются как есть.
    """
    for k in range(tries):
        name, raw, params = build(seq * 16 + k, seed, random_start, **filters)
        try:
            payload = arena.build_payload(raw, name)
            ctx = _bc(payload)
            if ctx.hostile_targets() and ctx.src.is_alive and payload.get("weapons"):
                params = dict(params, has_choke=len(chokepoint_cells(ctx)) > 0)
                return name, raw, params
        except Exception:
            continue
    return None


def generate(count: int, seed: int, random_start: Optional[bool] = None,
             **filters) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """count валидных независимых сценариев; имена уникальны, ho_*/ho2_* не производятся."""
    out: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    seen = set()
    seq = 0
    while len(out) < count and seq < count * 4:
        built = build_valid(seq, seed, random_start=random_start, **filters)
        seq += 1
        if built and built[0] not in seen:
            seen.add(built[0])
            out.append(built)
    return out


# Профиль Этапа 1: равные милишники 1в1 на пустом поле, каноническая расстановка.
# melee-арсеналы (только ближний бой), поле small (дистанция сближается за 1-2 хода).
DUEL_ARSENALS: Sequence[str] = ("sword", "greatsword", "two_melee")
DUEL_FILTERS: Dict[str, Any] = {
    "archetype": "duel", "classes": ["melee"], "arsenals": DUEL_ARSENALS,
    "n_side": 1, "wall_profile": "open", "field_profile": "small",
}


def generate_duels(count: int, seed: int) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """count melee-дуэлей 1v1 без стен (teaching_plan §Этап 1): structured, честный A/B."""
    return generate(count, seed, random_start=False, **DUEL_FILTERS)


# Профили дуэлей: зеркальные 1v1 одного класса + асимметрия по осям (Этапы 2–3).
# reach держит дистанцию за счёт class.reachFt=10 (оружие всё ещё ближнее); ranged — лук.
# Этап 3 добавляет роли tank (толстый медленный милишник) и mobile_archer (кайтующий лучник).
STAGE2_DUEL_PROFILES: Dict[str, Dict[str, Any]] = {
    "melee":         {"classes": ["melee"],         "arsenals": ("sword", "greatsword", "two_melee")},
    "fast":          {"classes": ["fast"],          "arsenals": ("sword", "two_melee")},
    "reach":         {"classes": ["reach"],         "arsenals": ("sword", "greatsword", "two_melee")},
    "ranged":        {"classes": ["ranged"],        "arsenals": ("bow",)},
    "mobile_archer": {"classes": ["mobile_archer"], "arsenals": ("bow",)},
    "tank":          {"classes": ["tank"],          "arsenals": ("greatsword", "two_melee")},
}
_STAGE2_GEOM: Dict[str, Any] = {"n_side": 1, "wall_profile": "open", "field_profile": "small"}

# Матрица неравных пар Этапа 3 (§Этап 3): unordered-классы. generate_stage3_pool раскрывает
# каждую пару в ОБЕИХ перестановках состава, чтобы ни один класс не сидел в выгодной зоне.
STAGE3_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("ranged", "melee"),
    ("reach", "fast"),
    ("tank", "melee"),
    ("mobile_archer", "melee"),
    ("ranged", "fast"),
    ("tank", "reach"),
)


def _retag(pool: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
           prefix: str) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """Уникальные group_id по профилю: разные классы/пары не коллидуют в split по группам."""
    out: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    for i, (_name, raw, params) in enumerate(pool):
        nm = "%s_%03d" % (prefix, i)
        p = dict(params)
        p["group_id"] = nm
        out.append((nm, raw, p))
    return out


def generate_mirror_duels(cls: str, count: int, seed: int
                          ) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """count ЗЕРКАЛЬНЫХ 1v1 дуэлей класса cls (Этап 2): обе стороны равны по силам и оружию
    (mirror=True), structured — побеждает тактика/очерёдность, а не удача в броске статов."""
    prof = STAGE2_DUEL_PROFILES[cls]
    pool = generate(count, seed, random_start=False, archetype="duel", mirror=True,
                    classes=prof["classes"], arsenals=prof["arsenals"], **_STAGE2_GEOM)
    return _retag(pool, "s2_%s" % cls)


def _asym_pool(cls_a: str, cls_b: str, count: int, seed: int,
               prefix: str) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """count 1v1 A=cls_a vs B=cls_b, structured; единый путь для асимметрии Этапов 2–3."""
    pa, pb = STAGE2_DUEL_PROFILES[cls_a], STAGE2_DUEL_PROFILES[cls_b]
    pool = generate(count, seed, random_start=False, archetype="duel",
                    classes=pa["classes"], foe_classes=pb["classes"],
                    arsenals=pa["arsenals"], foe_arsenals=pb["arsenals"], **_STAGE2_GEOM)
    return _retag(pool, prefix)


def generate_asym_duels(cls_a: str, cls_b: str, count: int, seed: int
                        ) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """count асимметричных 1v1 (сторона A=cls_a vs сторона B=cls_b), structured (Этап 2 гейт)."""
    return _asym_pool(cls_a, cls_b, count, seed, "s2_%sv%s" % (cls_a, cls_b))


def generate_stage3_pool(count_each: int, seed: int, pairs: Optional[Sequence[Tuple[str, str]]] = None
                         ) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """Неравные дуэли Этапа 3: каждая unordered-пара в ОБЕИХ перестановках состава (§1.9).

    count_each сцен на каждый УПОРЯДОЧЕННЫЙ вариант; для (a,b) выдаём и a×b, и b×a — тогда у
    каждого класса равное число боёв на A- и на B-зоне, и исход решают тактика/класс, а не
    то, какой стороне досталась выгодная геометрия. Имена s3_*, не коллидируют с s2_*.
    """
    out: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    for a, b in (pairs if pairs is not None else STAGE3_PAIRS):
        for x, y in ((a, b), (b, a)):
            out += _asym_pool(x, y, count_each, seed, "s3_%sv%s" % (x, y))
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
