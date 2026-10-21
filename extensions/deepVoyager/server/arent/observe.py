# arent/observe.py — payload /plan -> наблюдение схемы v1 (spec.SCHEMA).
#
# Ничего нового о бое не выдумываем: берём BattleContext (он умеет разбирать payload и
# считать клетки/враждебность) и дополняем его тем, что планировщик знает, но в /plan
# сегодня не видит: КД, бонус атаки, линия видимости. Поля ac/toHit/rangeFt/cr читаются
# из ctx.raw["npcs"] — сырых записей токена (planner/payload.py их не выбрасывает),
# поэтому старый клиент без этих полей не ломается: 0, и hit_chance() откатится на
# rules.hitChance.
from typing import Any, Dict, List, Optional, Tuple

from collections import deque

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


def _walls_in_view(ctx: BattleContext, me_cell: Cell) -> float:
    """Сколько стен, мешающих обзору, попадают в патч вокруг наблюдателя."""
    n = 0
    for w in ctx.walls:
        if w.sight <= 0:
            continue
        cell = ctx.scene.cell_of((w.ax + w.bx) / 2, (w.ay + w.by) / 2)
        if abs(cell[0] - me_cell[0]) <= spec.PATCH_R and abs(cell[1] - me_cell[1]) <= spec.PATCH_R:
            n += 1
    return float(n)


def _bfs_steps(pf: SimplePathfinder, ctx: BattleContext, src: Cell, goal: Cell, cap: int) -> int:
    """Клеток-шагов от src до goal по свободным клеткам (стены/край закрыты), не дальше cap."""
    if src == goal:
        return 0
    seen, queue = {src}, deque([(src, 0)])
    while queue:
        (r, c), dist = queue.popleft()
        if dist >= cap:
            continue
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (r + dr, c + dc)
            if nxt in seen or not (0 <= nxt[0] < ctx.scene.rows and 0 <= nxt[1] < ctx.scene.cols):
                continue
            if not pf._cell_valid(nxt[0], nxt[1], skip_npcs=True):
                continue
            if nxt == goal:
                return dist + 1
            seen.add(nxt)
            queue.append((nxt, dist + 1))
    return cap


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


def observe(ctx: BattleContext, initiative: Optional[Tuple[str, ...]] = None,
            actor: Optional[str] = None) -> Dict[str, Any]:
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
    ally_rows = [build(tok, False) for tok in allies][:spec.K_ALLIES]
    best = max(ctx.weapons, key=lambda w: w.expected_damage, default=None)
    result: Dict[str, Any] = {
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
        "allies": ally_rows,
        "others": [build(tok, False) for tok in others],
        "grid": _grid(ctx, me_cell, [(tok, "E") for tok in hostiles]
                      + [(tok, "A") for tok in allies] + [(tok, "T") for tok in others]),
    }
    _stamp_features(result, ctx, me_cell, enemies, ally_rows, initiative, actor)
    return result


def _stamp_features(result: Dict[str, Any], ctx: BattleContext, me_cell: Cell,
                    enemies: List[Dict[str, Any]], ally_rows: List[Dict[str, Any]],
                    initiative: Optional[Tuple[str, ...]], actor: Optional[str]) -> None:
    """Дополняет наблюдение признаками v2: террейн (всегда) и инициативу (когда задан порядок)."""
    me = result["me"]
    live = [e for e in enemies if e["alive"]]
    me["hasLosToNearestEnemy"] = 1.0 if any(e["los"] for e in live) else 0.0
    me["wallsInView"] = _walls_in_view(ctx, me_cell)
    near = min(live, key=lambda e: e["dist"], default=None)
    if near is None:
        me["pathLenFrac"] = 0.0
    else:
        goal = (me_cell[0] + near["dy"], me_cell[1] + near["dx"])
        me["pathLenFrac"] = round(_bfs_steps(SimplePathfinder(ctx.raw), ctx, me_cell, goal,
                                             spec.PATCH_SIZE) / spec.PATCH_SIZE, 4)
    if not initiative:
        return
    rank = {uid: i for i, uid in enumerate(initiative)}
    cur, big = (actor or ctx.src_id), len(initiative) + 1
    for e in enemies:
        e["initiativeIndex"] = rank.get(e["id"], 0)
        e["isNextToAct"] = (e["id"] == cur)
    for a in ally_rows:
        a["initiativeIndex"] = rank.get(a["id"], 0)
    team_a = [ctx.src_id] + [a["id"] for a in ally_rows]
    cur_rank = rank.get(cur, big)
    acted = sum(1 for uid in team_a if rank.get(uid, big) < cur_rank)
    me["alliesActedFraction"] = round(acted / len(team_a), 4) if team_a else 0.0


def observe_payload(payload: Dict[str, Any], initiative: Optional[Tuple[str, ...]] = None,
                    actor: Optional[str] = None) -> Dict[str, Any]:
    """Запрос /plan -> наблюдение v2 (JSON-пригодный словарь — для дампа и кодировщика)."""
    return observe(BattleContext.from_payload(payload), initiative, actor)
