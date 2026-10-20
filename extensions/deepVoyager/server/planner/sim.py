# planner/sim.py — симуляция одного раунда боя (пункт 5 todo.md).
#
# Отдельной модели боя нет: Simulation пересобирает BattleContext, поэтому Scorer,
# best_strike и quin работают на симулированном состоянии как на живом. Враги отвечают
# одним жадным ходом, урон — ожиданием (planner/dice.py) с множителем rules.hitChance.
import math
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Tuple

from planner.action import ACTION_MOVE, ACTION_TARGET, ACTION_USE, Action
from planner.action import move_action, target_action, use_action
from planner.context import BattleContext
from planner.explore import best_strike, legal_steps
from planner.geometry import DIR_VECTORS, Cell, apply_moves, cell_distance, within_reach
from planner.payload import parse_tokens
from planner.pathfinding import PathfindingService
from planner.points import tuning
from planner.scoring import Scorer


@dataclass(frozen=True)
class Unit:
    """Юнит симуляции: клетка, hp и параметры, с которыми он ходит и бьёт."""
    id: str
    cell: Cell
    hp: float
    speed_steps: int
    damage_avg: float
    reach_cells: float
    chance: float               # вероятность попадания его атаки
    hostile_to_hero: bool

    @property
    def is_alive(self) -> bool:
        return self.hp > 0


class Simulation:
    """Состояние боя после симулированных ходов. Исходный контекст не мутируется."""

    def __init__(self, base: BattleContext, units: Dict[str, Unit], hero_id: str,
                 target_id: Optional[str] = None, hero_dead: bool = False):
        self.base, self.units, self.hero_id = base, units, hero_id
        self._target_id, self.hero_dead, self._pf = target_id, hero_dead, None

    @classmethod
    def of(cls, context: BattleContext) -> "Simulation":
        """Герой — src запроса, враги — hostile_targets(); союзников пока не симулируем (долг)."""
        hostile = {t.id for t in context.hostile_targets()}
        units = {t.id: Unit(t.id, context.cell_of(t), float(t.hp_current), t.sim_speed_steps,
                            t.sim_damage_avg, t.sim_reach_cells, t.sim_hit_chance,
                            t.id in hostile) for t in context.tokens}
        best = max(context.weapons, key=lambda w: w.expected_damage, default=None)
        if best and context.src_id in units:      # урон героя — из его оружия, а не из «1d8»
            units[context.src_id] = replace(units[context.src_id], damage_avg=best.expected_damage)
        return cls(context, units, context.src_id, context.target_id)

    @property
    def hero(self) -> Unit:
        return self.units[self.hero_id]

    @property
    def foes(self) -> Tuple[Unit, ...]:
        return tuple(u for u in self.units.values() if u.hostile_to_hero and u.is_alive)

    @property
    def cells(self) -> Dict[str, Cell]:
        return {uid: u.cell for uid, u in self.units.items()}

    @property
    def hp(self) -> Dict[str, float]:
        return {uid: u.hp for uid, u in self.units.items()}

    def _others(self, exclude: str) -> Dict[str, Cell]:
        """Клетки живых токенов: вставать на чужую клетку нельзя (D&D 5e)."""
        return {uid: u.cell for uid, u in self.units.items() if uid != exclude and u.is_alive}

    def _raw(self) -> Dict[str, Any]:
        """Копия raw с симулированными позициями и hp — чтобы quin видел реальность."""
        gs, npcs = self.base.scene.grid_size, []
        for n in self.base.raw.get("npcs") or []:
            unit, m = self.units.get(n["id"]), dict(n)
            if unit is not None:
                m["x"], m["y"] = int(unit.cell[1] * gs), int(unit.cell[0] * gs)
                m["center"] = {"x": m["x"] + m["width"] / 2, "y": m["y"] + m["height"] / 2}
                m["hp"] = {**(n.get("hp") or {}), "current": int(math.ceil(unit.hp))}
            npcs.append(m)
        return {**self.base.raw, "npcs": npcs}

    def context_for(self, unit_id: str) -> BattleContext:
        """Тот же бой, но после симулированных ходов; src — указанный токен."""
        raw, target = self._raw(), self._target_id
        if target is not None and not self.units[target].is_alive:
            target = None              # мёртвая цель не должна возвращаться в hostile_targets
        return BattleContext(scene=self.base.scene, tokens=tuple(parse_tokens({"npcs": raw["npcs"]})),
                             walls=self.base.walls, src_id=unit_id, target_id=target, raw=raw,
                             speed_steps=self.base.speed_steps, weapons=self.base.weapons)

    @property
    def pf(self):
        """Один PathfindingService на состояние: npc_rects пекутся в __init__ quin."""
        if self._pf is None:
            self._pf = PathfindingService(self.context_for(self.hero_id))._finder
        return self._pf

    def apply_hero(self, actions: List[Action]) -> "Simulation":
        """Герой сходил: движение + удары. Мёртвый враг выпадет из foes (hp <= 0)."""
        t = tuning()
        dirs = [a.conf.get("direction") for a in actions if a.action == ACTION_MOVE]
        cell = apply_moves(self.hero.cell, [d for d in dirs if d in DIR_VECTORS])
        units = {**self.units, self.hero_id: replace(self.hero, cell=cell)}
        aimed = next((a.conf.get("id") for a in reversed(actions) if a.action == ACTION_TARGET),
                     self._target_id)
        for a in (x for x in actions if x.action == ACTION_USE):
            weapon = self.base.weapon(a.conf.get("itemId", ""))
            foe = units.get(aimed or "")
            reach = weapon.doubt_cells if weapon else t.default_enemy_reach_cells
            if foe is None or not foe.is_alive or not within_reach(cell, foe.cell, reach):
                continue        # не достать: ход состоялся, урона нет
            # своего КД у героя в данных нет (долг) — попадание по общему правилу
            damage = (weapon.expected_damage if weapon else t.unknown_damage_avg) * t.hit_chance
            units[aimed] = replace(foe, hp=foe.hp - damage)
        return Simulation(self.base, units, self.hero_id, self._target_id)

    def _approach(self, unit: Unit, hero_cell: Cell) -> Unit:
        """Жадное сближение: шаг, строго уменьшающий дистанцию, пока идёт."""
        for _ in range(unit.speed_steps):
            dist, step = cell_distance(unit.cell, hero_cell), unit
            blocked = frozenset(self._others(unit.id).values())
            for _d, cell in legal_steps(self.pf, *unit.cell, unit.id, unit.cell, occupied=blocked):
                if cell_distance(cell, hero_cell) < dist:
                    dist, step = cell_distance(cell, hero_cell), replace(unit, cell=cell)
            if step.cell == unit.cell:
                break
            unit = step
        return unit

    def foes_act(self) -> Tuple["Simulation", float]:
        """Ответ врагов за раунд: (состояние, штраф) — урон*шанс за факт удара + смерть."""
        t, units, penalty = tuning(), dict(self.units), 0.0
        for foe in self.foes:
            hero = units[self.hero_id]
            if not hero.is_alive:
                break                          # дожимать мёртвого смысла нет
            unit = foe
            if not within_reach(unit.cell, hero.cell, unit.reach_cells):
                unit = self._approach(unit, hero.cell)
                units[unit.id] = unit
            hero = units[self.hero_id]
            if within_reach(unit.cell, hero.cell, unit.reach_cells):
                penalty += t.damage_penalty * unit.chance      # штраф за сам факт урона
                units[self.hero_id] = replace(hero, hp=hero.hp - unit.damage_avg * unit.chance)
        dead = not units[self.hero_id].is_alive
        return (Simulation(self.base, units, self.hero_id, self._target_id, dead),
                penalty + (t.death_penalty if dead else 0.0))

    def advance(self, actions: List[Action]) -> Tuple["Simulation", float]:
        """Прогон раунда: значение = очки плана глазами Scorer + ответ врагов."""
        state, penalty = self.apply_hero(actions).foes_act()
        return state, Scorer().score(self.context_for(self.hero_id), actions) + penalty

    def round_value(self, actions: List[Action]) -> float:
        """Значение раунда; на depths=1 совпадает с очками сегодняшнего greedy плана."""
        return self.advance(actions)[1]

    def hero_options(self) -> List[List[Action]]:
        """Компактный набор ходов героя в глубине: остаться + лучшие shallow_k одношаговых."""
        t, ctx = tuning(), self.context_for(self.hero_id)
        enemies = ctx.hostile_targets()
        if not enemies:
            return []
        steps: Dict[Cell, List[str]] = {self.hero.cell: []}
        for d, cell in legal_steps(self.pf, *self.hero.cell, self.hero_id, self.hero.cell,
                                   occupied=frozenset(self._others(self.hero_id).values())):
            steps.setdefault(cell, [d])
        scored = []
        for cell, dirs in steps.items():
            strike = best_strike(ctx, cell, enemies, t)
            target = strike[0] if strike else min(
                enemies, key=lambda e: cell_distance(cell, ctx.cell_of(e)))
            actions = [target_action(target.id)] + [move_action(d) for d in dirs]
            if strike:
                actions.append(use_action(strike[1].id))
            scored.append((-self.round_value(actions), cell, actions))
        scored.sort(key=lambda s: (s[0], s[1]))
        return [actions for _v, _c, actions in scored[:max(1, t.shallow_k)]]


def rollout(context: BattleContext, actions: List[Action], rounds: int) -> float:
    """Метрика линии: план + жадная политика героя ещё N раундов — одной шкалой для
    greedy (rounds=1) и lookahead: считает симуляция, а не оценка планировщика."""
    state, total, line = Simulation.of(context), 0.0, list(actions)
    for _ in range(max(1, int(rounds))):
        state, value = state.advance(line)
        total += value
        if state.hero_dead:
            break
        options = state.hero_options()
        line = options[0] if options else []
    return total
