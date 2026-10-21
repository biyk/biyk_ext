# arent/slots_v3.py — пространство действий SCHEMA=3: куда бить × в кого × чем × где закончить.
#
# v2 (slots.py) выбирает одну клетку = финальную, а sim бьёт из неё; «выстрелил — спрятался»
# невыразимо. Здесь слот головы клеток — это ПЛАН ХОДА: пара (attack_cell, end_cell) с
# маршрутами до позиции атаки и из неё, уложенная в бюджет движения (cost_in + cost_out <=
# speed_steps). Порядок декодирования: target -> move(dirs_in) -> use -> move(dirs_out); его
# исполняет sim.apply_actor_seq (удар из attack_cell, а не из end_cell). Цели/оружие — как в v2
# (последний слот = «не атаковать»). v2-пространство остаётся в slots.py нетронутым.
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from planner.action import ACTION_MOVE, ACTION_TARGET, ACTION_USE
from planner.action import move_action, target_action, use_action
from planner.context import BattleContext
from planner.explore import reachable_paths
from planner.geometry import Cell, apply_moves, cell_distance
from planner.pathfinding import PathfindingService
from arent import spec, spec3

Cell2 = Tuple[int, int]


@dataclass
class SlotsV3:
    """Слоты v3: plans (move-plan'ы) × targets × weapons. Индексы = порядок списков."""
    plans: List[Dict[str, Any]] = field(default_factory=list)
    targets: List[Dict[str, Any]] = field(default_factory=list)
    weapons: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def n_plans(self) -> int:
        return len(self.plans)


def _cell_of(ctx: BattleContext, token_id: str) -> Cell:
    tok = ctx.token(token_id)
    return ctx.cell_of(tok) if tok else ctx.src_cell


def _nearest(cell: Cell, enemies: List[Dict[str, Any]], ctx: BattleContext) -> float:
    if not enemies:
        return 0.0
    return min(cell_distance(cell, _cell_of(ctx, e["id"])) for e in enemies)


def build(ctx: BattleContext, obs: Dict[str, Any]) -> SlotsV3:
    """Перечислить move-plan'ы (attack_cell, end_cell) в бюджете; усечь до K_MOVEPLAN."""
    pf = PathfindingService(ctx)._finder
    origin = ctx.src_cell
    enemies = [e for e in obs["enemies"] if e["hostile"] and e["alive"]]
    reach_from_origin = reachable_paths(pf, origin, ctx.src_id, ctx.speed_steps)
    plans: List[Dict[str, Any]] = []
    for attack_cell, dirs_in in reach_from_origin.items():
        cost_in = len(dirs_in)
        remaining = ctx.speed_steps - cost_in
        if remaining < 0:
            continue
        for end_cell, dirs_out in reachable_paths(pf, attack_cell, ctx.src_id, remaining).items():
            plans.append(_plan(ctx, origin, attack_cell, end_cell, dirs_in, dirs_out, cost_in))
    # приоритет: короткие суммарные маршруты, ближе к врагу, детерминированный порядок координат
    plans.sort(key=lambda p: (p["costTotal"], _nearest(p["attack_cell"], enemies, ctx),
                              p["attack_cell"], p["end_cell"]))
    plans = plans[:spec3.K_MOVEPLAN]
    return SlotsV3(plans=plans, targets=enemies[:spec.K_TARGETS],
                   weapons=[w for w in obs["weapons"][:spec.K_WEAPONS]])


def _plan(ctx, origin, attack_cell, end_cell, dirs_in, dirs_out, cost_in) -> Dict[str, Any]:
    cost_out = len(dirs_out)
    return {
        "attack_cell": attack_cell, "end_cell": end_cell,
        "dirs_in": list(dirs_in), "dirs_out": list(dirs_out),
        "adx": attack_cell[1] - origin[1], "ady": attack_cell[0] - origin[0],
        "edx": end_cell[1] - origin[1], "edy": end_cell[0] - origin[0],
        "adist": round(cell_distance(origin, attack_cell), 2),
        "edist": round(cell_distance(origin, end_cell), 2),
        "costIn": cost_in, "costOut": cost_out, "costTotal": cost_in + cost_out,
        "retreatToOrigin": end_cell == origin and attack_cell != origin,
        "pureMove": attack_cell == end_cell,
    }


def plan_index(slots: SlotsV3, attack_cell: Cell, end_cell: Cell) -> int:
    return next((i for i, p in enumerate(slots.plans)
                 if p["attack_cell"] == attack_cell and p["end_cell"] == end_cell), -1)


def attackable_v3(slots: SlotsV3, ctx: BattleContext, plan_i: int, target_i: int,
                  weapon_i: int) -> bool:
    """Легально ли три: цель жива, план в слотах, оружие ДОСТАЁТ ЦЕЛЬ ИЗ ПОЗИЦИИ АТАКИ."""
    if not (0 <= plan_i < slots.n_plans) or target_i < 0 or weapon_i < 0:
        return False
    if not (0 <= target_i < len(slots.targets) and 0 <= weapon_i < len(slots.weapons)):
        return False
    enemy, weapon = slots.targets[target_i], slots.weapons[weapon_i]
    if not enemy["alive"]:
        return False
    dist = cell_distance(slots.plans[plan_i]["attack_cell"], _cell_of(ctx, enemy["id"]))
    return dist <= float(weapon["doubtCells"]) + 0.5


def _real(index: int, count: int) -> int:
    return index if 0 <= index < count else -1


def decode(slots: SlotsV3, label: Dict[str, int]) -> List[Any]:
    """(plan,target,weapon) -> действия в БОЕВОМ порядке: target, move(до атаки), use, move(уход)."""
    actions: List[Any] = []
    target_i = _real(label.get("target", spec.NONE_SLOT), len(slots.targets))
    weapon_i = _real(label.get("weapon", spec.NONE_SLOT), len(slots.weapons))
    plan = slots.plans[label["plan"]] if 0 <= label.get("plan", -1) < slots.n_plans else None
    if target_i >= 0:
        actions.append(target_action(slots.targets[target_i]["id"]))
    if plan is not None:
        actions += [move_action(d) for d in plan["dirs_in"]]
    if weapon_i >= 0:
        actions.append(use_action(slots.weapons[weapon_i]["id"]))
    if plan is not None:
        actions += [move_action(d) for d in plan["dirs_out"]]
    return actions


def label_of(ctx: BattleContext, slots: SlotsV3, actions: List[Any]) -> Optional[Dict[str, int]]:
    """Последовательность действий -> (plan,target,weapon); None, если endpoints нет в слотах.

    Делим по первому USE: MOVE до него — подход к позиции атаки, MOVE после — отступление.
    v2-план учителя (все move перед use) даёт end_cell == attack_cell — он отображается в v3.
    """
    origin = ctx.src_cell
    use_at = next((i for i, a in enumerate(actions) if a.action == ACTION_USE), None)
    moves = [a.conf.get("direction") for a in actions if a.action == ACTION_MOVE
             and a.conf.get("direction")]
    if use_at is None:
        dirs_in, dirs_out = moves, []
    else:
        in_order = [a for a in actions[:use_at] if a.action == ACTION_MOVE]
        out_order = [a for a in actions[use_at + 1:] if a.action == ACTION_MOVE]
        dirs_in = [a.conf.get("direction") for a in in_order if a.conf.get("direction")]
        dirs_out = [a.conf.get("direction") for a in out_order if a.conf.get("direction")]
    attack_cell = apply_moves(origin, dirs_in)
    end_cell = apply_moves(attack_cell, dirs_out)
    plan_i = plan_index(slots, attack_cell, end_cell)
    if plan_i < 0:
        return None
    aimed = next((a.conf.get("id") for a in reversed(actions) if a.action == ACTION_TARGET), None)
    used = next((a.conf.get("itemId") for a in actions if a.action == ACTION_USE), None)
    target_i = next((i for i, t in enumerate(slots.targets) if t["id"] == aimed), spec.NONE_SLOT)
    weapon_i = next((i for i, w in enumerate(slots.weapons) if w["id"] == used), spec.NONE_SLOT)
    return {"plan": plan_i, "target": target_i, "weapon": weapon_i}
