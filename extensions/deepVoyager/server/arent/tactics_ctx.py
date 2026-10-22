# arent/tactics_ctx.py — детекторное представление шага из ground-truth (§2.1, §11.1 layer 2).
#
# build_step_ctx превращает переход Simulation (prev_units -> units) + выбранный ход актёра в
# чистый StepCtx для детекторов. Всё берётся из симуляции/стен (клетки, hp, LOS, reach), НИЧЕГО
# — из наблюдения модели: трасс полигона знает реальность, даже если сеть признак не видит.
#
# Полей класса/роли в payload симуляции нет (scenarios._token их не несёт), поэтому роль выводим
# из ground-truth-признаков: дальнобойность по reach_cells, «танк» по потолку HP. Это приближение
# зафиксировано константами ниже; когда роль придёт в данные — заменим вывод на чтение.
from __future__ import annotations

from typing import Dict, Optional, Tuple

from arent.tactics import StepCtx, UnitView
from planner.action import ACTION_TARGET, ACTION_USE
from planner.geometry import cell_distance
from planner.initiative import side_of
from planner.los import has_los, sight_segments

RANGE_MIN_CELLS = 3.0     # reach_cells >= этого => юнит считаем дальнобойным (лук 30фт=6)
TANK_HP_MIN = 24.0        # hp_max >= этого => «танк» (совпадает с нижней границей tank в UNIT_CLASSES)
MELEE_TOL = 0.6           # допуск «вплотную» для contacts/reach (как reachTolerance в движке)


def _is_ranged(reach_cells: float) -> bool:
    return reach_cells >= RANGE_MIN_CELLS


def _derive_role(hp_max: float, reach_cells: float) -> str:
    if _is_ranged(reach_cells):
        return "ranged"
    return "tank" if hp_max >= TANK_HP_MIN else "melee"


def _view(u, los: bool, hp_max: float) -> UnitView:
    return UnitView(
        id=u.id, cell=u.cell, hp=u.hp, hp_max=hp_max, alive=u.is_alive,
        reach=u.reach_cells, speed=u.speed_steps, dmg=u.damage_avg, chance=u.chance,
        ranged=_is_ranged(u.reach_cells), role=_derive_role(hp_max, u.reach_cells), los=los,
    )


def _contacts(cell, enemies) -> int:
    """Сколько живых врагов бьют в упор из клетки cell (их melee-reach накрывает cell)."""
    return sum(1 for e in enemies
               if e.is_alive and not _is_ranged(e.reach_cells)
               and cell_distance(cell, e.cell) <= e.reach_cells + MELEE_TOL)


def action_outcome(actions) -> Tuple[bool, Optional[str]]:
    """(атаковал ли актёр, id цели) из декодированного хода: атака = есть USE, цель = последний TARGET."""
    attacked = any(a.action == ACTION_USE for a in actions)
    target_id = None
    for a in actions:
        if a.action == ACTION_TARGET:
            target_id = a.conf.get("id") or target_id
    return attacked, target_id


def build_step_ctx(sim, prev_units: Dict, units: Dict, actor_id: str, cell_after: Tuple[int, int],
                   target_id: Optional[str], attacked: bool, round_index: int,
                   hp_max: Dict[str, float], prior_allies_on_target: int = 0,
                   prior_ally_targets: Tuple[str, ...] = ()) -> StepCtx:
    """StepCtx одного хода актёра из перехода Simulation (ground-truth)."""
    base, hero_id = sim.base, sim.hero_id
    sight = sight_segments(base)
    actor_prev = prev_units[actor_id]
    actor_after = units[actor_id]
    actor_side = side_of(actor_prev, hero_id)

    foes, allies = [], []
    for uid, u in units.items():
        s = side_of(u, hero_id)
        if s is None or not u.is_alive:
            continue
        if uid == actor_id:
            continue
        if actor_side is not None and s == actor_side:
            allies.append(_view(u, True, hp_max.get(uid, max(u.hp, 1))))
        elif actor_side is not None:
            los = has_los(base, cell_after, u.cell, sight)
            foes.append(_view(u, los, hp_max.get(uid, max(u.hp, 1))))

    enemy_units = [u for uid, u in units.items()
                   if u.is_alive and side_of(u, hero_id) not in (None, actor_side)]
    any_seen_after = any(has_los(base, cell_after, u.cell, sight) for u in enemy_units)
    any_seen_before = any(has_los(base, actor_prev.cell, u.cell, sight) for u in enemy_units)

    tgt_before = prev_units.get(target_id) if target_id else None
    dmg_expect = round(actor_after.damage_avg * actor_after.chance, 4) if attacked else 0.0

    a_max = hp_max.get(actor_id, max(actor_prev.hp, 1))
    actor_view = UnitView(
        id=actor_id, cell=actor_prev.cell, hp=actor_prev.hp, hp_max=a_max,
        alive=actor_after.is_alive, reach=actor_after.reach_cells, speed=actor_after.speed_steps,
        dmg=actor_after.damage_avg, chance=actor_after.chance,
        ranged=_is_ranged(actor_after.reach_cells), role=_derive_role(a_max, actor_after.reach_cells),
        los=True,
    )

    return StepCtx(
        actor=actor_view, cell_after=cell_after,
        foes=tuple(foes), allies=tuple(allies),
        target_id=target_id, attacked=attacked,
        moved=(cell_after != actor_prev.cell),
        strike_range=actor_after.reach_cells, dmg_expect=dmg_expect,
        target_hp_before=float(tgt_before.hp) if tgt_before is not None else 0.0,
        took_damage=(actor_after.hp < actor_prev.hp - 1e-9),
        cover_before=(bool(enemy_units) and not any_seen_before),
        cover_after=(bool(enemy_units) and not any_seen_after),
        in_reach_after=_contacts(cell_after, enemy_units) >= 1,
        contacts_before=_contacts(actor_prev.cell, enemy_units),
        contacts_after=_contacts(cell_after, enemy_units),
        round_index=round_index,
        prior_allies_on_target=prior_allies_on_target,
        prior_ally_targets=prior_ally_targets,
    )
