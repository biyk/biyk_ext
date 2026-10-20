# arent/observe.py — payload /plan -> наблюдение схемы v1 (spec.SCHEMA).
#
# Ничего нового о бое не выдумываем: берём BattleContext (он умеет разбирать payload и
# считать клетки/враждебность) и дополняем его тем, что планировщик знает, но в /plan
# сегодня не видит: КД, бонус атаки, линия видимости. Поля ac/toHit/rangeFt/cr читаются
# из ctx.raw["npcs"] — сырых записей токена (planner/payload.py их не выбрасывает),
# поэтому старый клиент без этих полей не ломается: 0, и hit_chance() откатится на
# rules.hitChance.
from typing import Any, Dict, List, Optional, Tuple

from libs.quin import SimplePathfinder
from planner.armament import SURE, best_attack
from planner.context import BattleContext, Token
from planner.geometry import cell_distance
from planner.points import tuning
from arent import spec

Cell = Tuple[int, int]
Point = Tuple[float, float]
Segment = Tuple[Point, Point]


def _raw_npcs(ctx: BattleContext) -> Dict[str, Dict[str, Any]]:
    """id токена -> его сырая запись npcs[] (там ac/toHit/rangeFt/cr, чего нет в Token)."""
    return {str(n.get("id")): n for n in (ctx.raw or {}).get("npcs") or []}


def _number(raw: Dict[str, Any], key: str) -> float:
    try:
        return float(raw.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def sight_segments(ctx: BattleContext) -> List[Segment]:
    """Стены, мешающие обзору: тот же геометрический тест, что у quin, но по флагу sight."""
    return [((w.ax, w.ay), (w.bx, w.by)) for w in ctx.walls if w.sight > 0]


def _center(ctx: BattleContext, cell: Cell) -> Point:
    gs = ctx.scene.grid_size
    return (cell[1] + 0.5) * gs, (cell[0] + 0.5) * gs


def has_los(ctx: BattleContext, a: Cell, b: Cell, segments: List[Segment]) -> bool:
    """Видно ли центр клетки b из центра клетки a: прямая не пересекает ни одной стены."""
    p1, p2 = _center(ctx, a), _center(ctx, b)
    return not any(SimplePathfinder._segment_intersect(p1, p2, s[0], s[1]) for s in segments)


def _classify(ctx: BattleContext) -> Tuple[List[Token], List[Token], List[Token]]:
    """Живые токены кроме src -> (враги, союзники той же группы, прочие/нейтральные)."""
    me = ctx.src
    hostiles, allies, others = list(ctx.hostile_targets()), [], []
    for tok in ctx.tokens:
        if tok.id == ctx.src_id or not tok.is_alive or ctx.is_hostile(tok):
            continue
        (allies if tok.disposition == me.disposition else others).append(tok)
    return hostiles, allies, others


def _entity(ctx: BattleContext, tok: Token, raw: Dict[str, Any], me_cell: Cell,
            sight: List[Segment], my_ac: float, my_melee: float, hostile: bool) -> Dict[str, Any]:
    """Токен -> запись наблюдения: геометрия, живучесть и угроза от него."""
    t = tuning()
    cell = ctx.cell_of(tok)
    dist = cell_distance(me_cell, cell)
    los = has_los(ctx, me_cell, cell, sight)
    chance = spec.hit_chance(_number(raw, "toHit"), my_ac, t.hit_chance) if hostile else 0.0
    reach = tok.sim_reach_cells
    range_cells = _number(raw, "rangeFt") / t.feet_per_cell
    return {
        "id": tok.id, "name": tok.name or tok.id,
        "dx": cell[1] - me_cell[1], "dy": cell[0] - me_cell[0], "dist": round(dist, 2),
        "hp": tok.hp_current, "hpMax": int(_number((raw or {}).get("hp") or {}, "max")),
        "ac": _number(raw, "ac"), "toHit": _number(raw, "toHit"),
        "dmgAvg": round(tok.sim_damage_avg, 2), "reachCells": round(reach, 2),
        "rangeCells": round(range_cells, 2), "speedCells": tok.sim_speed_steps,
        "hostile": hostile, "alive": tok.is_alive, "los": los,
        # успевает ли ударить по нам в ответный ход: достает сейчас или добежит за ход
        "canHitMe": bool(hostile and los and (dist <= reach or dist <= range_cells)),
        "canReachMe": bool(hostile and dist <= reach + tok.sim_speed_steps + 1),
        "inMyMelee": bool(hostile and dist <= my_melee),
        "chanceOnMe": round(chance, 3),
        "dmgToMe": round(chance * tok.sim_damage_avg, 2),
    }


def _grid(ctx: BattleContext, me_cell: Cell, marks: List[Tuple[Token, str]]) -> List[str]:
    """Патч поля (2R+1)^2: '#' стена/край, 'E' враг, 'A' союзник, 'T' прочий, '@' герой."""
    r = spec.PATCH_R
    occupied = {ctx.cell_of(tok): letter for tok, letter in marks}
    pf = SimplePathfinder(ctx.raw)
    rows = []
    for dr in range(-r, r + 1):
        line = ""
        for dc in range(-r, r + 1):
            cell = (me_cell[0] + dr, me_cell[1] + dc)
            if cell == me_cell:
                line += "@"
            elif cell in occupied:
                line += occupied[cell]
            else:
                free = (0 <= cell[0] < ctx.scene.rows and 0 <= cell[1] < ctx.scene.cols
                        and pf._cell_valid(cell[0], cell[1], skip_npcs=True))
                line += "." if free else "#"
        rows.append(line)
    return rows


def weapon_entry(weapon, enemies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Оружие: чем бьёт, как далеко и есть ли кому отвечать прямо сейчас."""
    mode: Optional[str] = None
    for e in enemies:
        if not e["los"] or not e["alive"]:
            continue
        found = best_attack([weapon], e["dist"])
        if found and (mode is None or found[1] == SURE):
            mode = found[1]
    return {
        "id": weapon.id, "name": weapon.name,
        "dmgAvg": round(weapon.expected_damage, 2), "toHit": weapon.attack_bonus,
        "sureCells": round(weapon.sure_cells, 2), "doubtCells": round(weapon.doubt_cells, 2),
        "ranged": bool(weapon.ranged), "thrown": bool(weapon.thrown),
        "reachesAny": mode is not None, "bestModeSure": mode == SURE,
    }


def observe(ctx: BattleContext) -> Dict[str, Any]:
    """Снимок боя глазами src-токена: hero / slots / enemies / allies / others / grid."""
    t = tuning()
    raws = _raw_npcs(ctx)
    me = ctx.src
    me_cell = ctx.src_cell
    sight = sight_segments(ctx)
    my_ac = _number(raws.get(me.id, {}), "ac")
    hostiles, allies, others = _classify(ctx)

    def build(tok: Token, hostile: bool) -> Dict[str, Any]:
        return _entity(ctx, tok, raws.get(tok.id, {}), me_cell, sight, my_ac,
                       max((w.sure_cells for w in ctx.weapons if not w.ranged), default=1.0),
                       hostile)

    enemies = sorted((build(tok, True) for tok in hostiles), key=lambda e: e["dist"])
    best = max(ctx.weapons, key=lambda w: w.expected_damage, default=None)
    return {
        "schema": spec.SCHEMA, "src": ctx.src_id, "target": ctx.target_id,
        "scene": {"cols": ctx.scene.cols, "rows": ctx.scene.rows,
                  "cellFt": t.feet_per_cell, "gridSize": ctx.scene.grid_size},
        "me": {
            "id": me.id, "name": me.name, "cell": list(me_cell), "hp": me.hp_current,
            "hpMax": int(_number((raws.get(ctx.src_id) or {}).get("hp") or {}, "max")),
            "ac": my_ac, "speedCells": ctx.speed_steps, "cr": _number(raws.get(ctx.src_id, {}), "cr"),
            "toHit": _number(raws.get(ctx.src_id, {}), "toHit"),
            "dmgAvg": round(best.expected_damage if best else t.unknown_damage_avg, 2),
            "reachCells": max((w.sure_cells for w in ctx.weapons if not w.ranged), default=1.0),
            "rangeCells": max((w.doubt_cells for w in ctx.weapons), default=1.0),
            "enemiesAlive": sum(1 for e in enemies if e["alive"]),
            "alliesAlive": len(allies),
            "incomingAvg": round(sum(e["dmgToMe"] for e in enemies if e["canHitMe"]), 2),
        },
        "weapons": [weapon_entry(w, enemies) for w in ctx.weapons],
        "enemies": enemies[:spec.K_TARGETS],
        "allies": [build(tok, False) for tok in allies][:spec.K_ALLIES],
        "others": [build(tok, False) for tok in others],
        "grid": _grid(ctx, me_cell, [(tok, "E") for tok in hostiles]
                      + [(tok, "A") for tok in allies] + [(tok, "T") for tok in others]),
    }


def observe_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Запрос /plan -> наблюдение v1 (JSON-пригодный словарь — для дампа и кодировщика)."""
    return observe(BattleContext.from_payload(payload))
