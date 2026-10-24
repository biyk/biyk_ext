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
from planner.los import los_clear, sight_segments
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


def _can_strike(ctx: BattleContext, cell: Cell, enemies: List[Dict[str, Any]],
                weapons: List[Dict[str, Any]], segments) -> bool:
    """Можно ли из клетки cell достать хоть одну живую цель (дистанция И LOS) хоть чем-то.

    Чистая функция состояния (стены/позиции/дальности из ctx+obs), поэтому serve и train
    ранжируют меню одинаково: приоритет слота определяет «можно ли отсюда реально ударить»,
    а не «сколько шагов». Дальность = та же doubt-зона + допуск 0.5, что attackable_v3.
    """
    if not weapons:
        return False
    for e in enemies:
        at = _cell_of(ctx, e["id"])
        dist = cell_distance(cell, at)
        if any(dist <= float(w["doubtCells"]) + 0.5 for w in weapons) \
                and los_clear(ctx, cell, at):
            return True
    return False


# Клеточный «почти вплотную» порог, синхронный с teacher_select.RANGE_MIN_CELLS: оружие,
# чья doubt-зона длиннее, считается дальним, и меню для него ранжится роль-осведомлённо.
RANGED_REACH_CELLS = 3.0


def _ideal_distance(origin: Cell, enemies: List[Dict[str, Any]], weapons: List[Dict[str, Any]],
                    ctx: BattleContext) -> float:
    """Целевая дистанция для дальнего бойца — функция состояния, детерминированная.

    band_lo = 1 + min(reachCells+speedCells) — вне зоны «враг допрыгнет и ударит» за один ход;
    сверху ограничиваем эффективной дальностью оружия (wreach+0.5) — дальше стрелять нельзя;
    и не увеличиваем против текущего d0 — если уже безопасно, держим позицию (hold),
    а не гоним актёра «к максимальной дистанции» (безусловного отступления нет).
    """
    d0 = _nearest(origin, enemies, ctx)
    band_lo = 1.0 + min(float(e["reachCells"]) + float(e["speedCells"]) for e in enemies)
    wreach = max((float(w["doubtCells"]) for w in weapons), default=1.0)
    return max(band_lo, min(d0, wreach + 0.5))


def _is_ranged(weapons: List[Dict[str, Any]]) -> bool:
    return bool(weapons) and max(float(w["doubtCells"]) for w in weapons) >= RANGED_REACH_CELLS


def build(ctx: BattleContext, obs: Dict[str, Any]) -> SlotsV3:
    """Перечислить move-plan'ы (attack_cell, end_cell) в бюджете; усечь до K_MOVEPLAN.

    ЭТАП 5 (часть 2): приоритет меню — релевантность позиции атаки, а не стоимость хода.
    Порядок (все ключи — функция состояния, детерминирован → serve и train одинаково):
      1) attack_cell, с которого кого-то достать (LOS+дальность), идёт первым;
      2) ближе к врагу;
      3) короче суммарный маршрут; 4) детерминированный порядок координат.
    Раньше сортировка по costTotal вытесняла дальние атакующие клетки учителя за K_MOVEPLAN,
    и ensure_plan вставлял их всегда в последний слот (47) — сеть училась выбирать позицию,
    а не содержимое плана. Релевантная сортировка оставляет план учителя на естественном
    (варьируемом) индексе, убирая позиционную утечку без изменения размерностей.
    """
    pf = PathfindingService(ctx)._finder
    origin = ctx.src_cell
    enemies = [e for e in obs["enemies"] if e["hostile"] and e["alive"]]
    weapons = obs["weapons"][:spec.K_WEAPONS]
    segments = sight_segments(ctx)
    reach_from_origin = reachable_paths(pf, origin, ctx.src_id, ctx.speed_steps)
    plans: List[Dict[str, Any]] = []
    for attack_cell, dirs_in in reach_from_origin.items():
        cost_in = len(dirs_in)
        remaining = ctx.speed_steps - cost_in
        if remaining < 0:
            continue
        for end_cell, dirs_out in reachable_paths(pf, attack_cell, ctx.src_id, remaining).items():
            plans.append(_plan(ctx, origin, attack_cell, end_cell, dirs_in, dirs_out, cost_in))
    # Ранжир: для ближнего — прежняя «страйк-далее-ближе-к-врагу» логика (ЭТАП 5, побитово);
    # для дальнобойного — роль-осведомлённая: близость к целевой дистанции ПОСЛЕ хода, что
    # даёт hold при уже удобной позиции и retreat при опасном контакте, не форсируя ни то,
    # ни другое (консультант: «Не задавать безусловное правило всегда отходить»).
    strike_bucket = lambda p: 0 if _can_strike(ctx, p["attack_cell"], enemies, weapons, segments) else 1  # noqa: E731
    if enemies and _is_ranged(weapons):
        ideal = _ideal_distance(origin, enemies, weapons, ctx)
        plans.sort(key=lambda p: (strike_bucket(p),
                                  round(abs(_nearest(p["end_cell"], enemies, ctx) - ideal), 3),
                                  p["costTotal"], p["attack_cell"], p["end_cell"]))
    else:
        plans.sort(key=lambda p: (strike_bucket(p), _nearest(p["attack_cell"], enemies, ctx),
                                  p["costTotal"], p["attack_cell"], p["end_cell"]))
    # Резерв hold: если стоять на месте легально (та план всегда в переборе: dirs=[]) и это
    # дальнобойный боец, hold обязан остаться в меню. Меняем местами с последним (наихудшим)
    # из усечённого списка — это genuine кандидат, а не фиктивное действие.
    if enemies and _is_ranged(weapons) and len(plans) > spec3.K_MOVEPLAN:
        hold = next((p for p in plans
                     if p["attack_cell"] == origin and p["end_cell"] == origin), None)
        kept = plans[:spec3.K_MOVEPLAN]
        if hold is not None and hold not in kept:
            kept[-1] = hold
        plans = kept
    else:
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


def split_turn(ctx: BattleContext, actions: List[Any]) -> Tuple[Cell, Cell, List[str], List[str]]:
    """Разрезать ход учителя на (attack_cell, end_cell, dirs_in, dirs_out) по первому USE.

    MOVE до первого USE — подход к позиции атаки, MOVE после — отступление. v2-ход учителя
    (все move перед use) даёт end_cell == attack_cell."""
    origin = ctx.src_cell
    use_at = next((i for i, a in enumerate(actions) if a.action == ACTION_USE), None)
    if use_at is None:
        in_order, out_order = [a for a in actions if a.action == ACTION_MOVE], []
    else:
        in_order = [a for a in actions[:use_at] if a.action == ACTION_MOVE]
        out_order = [a for a in actions[use_at + 1:] if a.action == ACTION_MOVE]
    dirs_in = [a.conf.get("direction") for a in in_order if a.conf.get("direction")]
    dirs_out = [a.conf.get("direction") for a in out_order if a.conf.get("direction")]
    attack_cell = apply_moves(origin, dirs_in)
    end_cell = apply_moves(attack_cell, dirs_out)
    return attack_cell, end_cell, dirs_in, dirs_out


def ensure_plan(slots: SlotsV3, ctx: BattleContext, actions: List[Any]) -> int:
    """Гарантировать план учителя в слотах (аналог slots.ensure_cell); вернуть его индекс.

    Перебор plan'ов усекается до K_MOVEPLAN по коротким маршрутам, а учитель часто выбирает
    дальнюю клетку (стрелять из-за укрытия / отойти) — без вставки её (attack,end) нет в
    слотах, label_of вернул бы None и пример потерялся. Вытесняем последний (наименее
    приоритетный) план, если мест нет.
    """
    attack_cell, end_cell, dirs_in, dirs_out = split_turn(ctx, actions)
    index = plan_index(slots, attack_cell, end_cell)
    if index >= 0:
        return index
    entry = _plan(ctx, ctx.src_cell, attack_cell, end_cell, dirs_in, dirs_out, len(dirs_in))
    if len(slots.plans) >= spec3.K_MOVEPLAN:
        slots.plans.pop()
    slots.plans.append(entry)
    return len(slots.plans) - 1


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
    # F-C: проверяем доступность ИЗ ПОЗИЦИИ АТАКИ (attack_cell), а не конечной клетки
    # (end_cell): «вышел из-за угла — выстрелил — вернулся» легально, если на момент
    # выстрела есть линия видимости. То же правило, что у sim.apply_actor_seq.
    attack_cell = slots.plans[plan_i]["attack_cell"]
    at = _cell_of(ctx, enemy["id"])
    dist = cell_distance(attack_cell, at)
    return dist <= float(weapon["doubtCells"]) + 0.5 and los_clear(ctx, attack_cell, at)


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

    Делим по первому USE (см. split_turn). v2-план учителя (все move перед use) даёт
    end_cell == attack_cell — он отображается в v3. Вызывать ПОСЛЕ ensure_plan.
    """
    attack_cell, end_cell, _in, _out = split_turn(ctx, actions)
    plan_i = plan_index(slots, attack_cell, end_cell)
    if plan_i < 0:
        return None
    aimed = next((a.conf.get("id") for a in reversed(actions) if a.action == ACTION_TARGET), None)
    used = next((a.conf.get("itemId") for a in actions if a.action == ACTION_USE), None)
    target_i = next((i for i, t in enumerate(slots.targets) if t["id"] == aimed), spec.NONE_SLOT)
    weapon_i = next((i for i, w in enumerate(slots.weapons) if w["id"] == used), spec.NONE_SLOT)
    return {"plan": plan_i, "target": target_i, "weapon": weapon_i}
