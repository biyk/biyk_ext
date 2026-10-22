# planner/sim.py — симуляция раунда: ходы по инициативе; Simulation пересобирает
# BattleContext глазами актёра (src/оружие/скорость — per-token, WP2), поэтому Scorer
# и quin работают на симулированном состоянии как на живом. Урон — ожиданием (dice.py).
import math
from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

from planner.action import ACTION_MOVE, ACTION_TARGET, ACTION_USE, Action
from planner.action import move_action, target_action, use_action
from planner.context import BattleContext
from planner.explore import best_strike, legal_steps
from planner.geometry import DIR_VECTORS, Cell, apply_moves, cell_distance
from planner.initiative import (Unit, allies_of, are_hostile, living_order,
                                next_living, roll_initiatives)
from planner.los import sight_segments, striking_distance
from planner.payload import actor_gear, parse_tokens
from planner.pathfinding import PathfindingService
from planner.points import tuning
from planner.scoring import Scorer


class Simulation:
    """Состояние боя после симулированных ходов. Исходный контекст не мутируется."""

    def __init__(self, base: BattleContext, units: Dict[str, Unit], hero_id: str,
                 target_id: Optional[str] = None, hero_dead: bool = False,
                 initiative_order: Tuple[str, ...] = ()):
        self.base, self.units, self.hero_id = base, units, hero_id
        self._target_id, self.hero_dead, self._pf = target_id, hero_dead, None
        self._sight = None
        self.initiative_order = tuple(initiative_order)

    @classmethod
    def of(cls, context: BattleContext, env_seed=None) -> "Simulation":
        """Команда героя (src + союзники) против врагов; инициатива — поле или d20 от env_seed."""
        hostile = {t.id for t in context.hostile_targets()}
        units = {t.id: Unit(t.id, context.cell_of(t), float(t.hp_current), t.sim_speed_steps,
                            t.sim_damage_avg, t.sim_reach_cells, t.sim_hit_chance,
                            t.id in hostile, t.initiative,
                            t.id != context.src_id and t.id not in hostile
                            and t.disposition == context.src.disposition
                            and t.disposition != 0)
                 for t in context.tokens}
        best = max(context.weapons, key=lambda w: w.expected_damage, default=None)
        if best and context.src_id in units:      # урон героя — из его оружия, а не из «1d8»
            units[context.src_id] = replace(units[context.src_id], damage_avg=best.expected_damage)
        combatants = [(u.id, u.initiative) for u in units.values() if u.is_alive
                      and (u.hostile_to_hero or u.ally_to_hero or u.id == context.src_id)]
        order = roll_initiatives(combatants, env_seed)
        return cls(context, units, context.src_id, context.target_id, initiative_order=order)

    @property
    def hero(self) -> Unit:
        return self.units[self.hero_id]

    @property
    def foes(self) -> Tuple[Unit, ...]:
        return tuple(u for u in self.units.values() if u.hostile_to_hero and u.is_alive)

    @property
    def allies(self) -> Tuple[Unit, ...]:
        """Живые союзники той же команды, что герой (сам герой и нейтральные не входят)."""
        return allies_of(self.units)

    @property
    def living_in_order(self) -> Tuple[str, ...]:
        return living_order(self.units, self.initiative_order)

    def next_to_act(self, after_uid: Optional[str] = None) -> Optional[str]:
        return next_living(self.units, self.initiative_order, after_uid)

    @property
    def cells(self) -> Dict[str, Cell]:
        return {uid: u.cell for uid, u in self.units.items()}

    @property
    def hp(self) -> Dict[str, float]:
        return {uid: u.hp for uid, u in self.units.items()}

    def _others(self, exclude: str) -> Dict[str, Cell]:
        """Клетки живых токенов: вставать на чужую клетку нельзя (D&D 5e)."""
        return {uid: u.cell for uid, u in self.units.items() if uid != exclude and u.is_alive}

    def _clone(self, units: Dict[str, Unit], hero_dead: bool = False) -> "Simulation":
        return Simulation(self.base, units, self.hero_id, self._target_id, hero_dead,
                          self.initiative_order)

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

    def _nearest_hostile(self, unit_id: str) -> Optional[str]:
        """Ближайший живой враг актёра (tiebreak по id) — цель «с его лица».

        Признак isTargeted в наблюдении (encode.entity_slot) симметричен по командам только
        если актёр видит помеченной СВОЮ цель. Глобальный _target_id задан с лица героя, для
        актёра другой команды это его союзник/он сам → isTargeted=0 → структурный перевес
        src/hero. Дистанция по клетке, порядок детерминирован.
        """
        actor = self.units.get(unit_id)
        if actor is None:
            return None
        foes = [u for u in self.units.values()
                if u.id != unit_id and u.is_alive and are_hostile(actor, u, self.hero_id)]
        if not foes:
            return None
        foes.sort(key=lambda u: (cell_distance(actor.cell, u.cell), u.id))
        return foes[0].id

    def _default_target_for(self, unit_id: str) -> Optional[str]:
        """Цель по умолчанию для действия/наблюдения актёра unit_id.

        Для героя сохраняем исходное поведение (клиентская payload-цель; мёртвая -> None).
        Для актёра другой команды перепривязываем к его собственному ближайшему врагу.
        """
        if unit_id == self.hero_id:
            t = self._target_id
            return t if (t is not None and self.units.get(t) and self.units[t].is_alive) else None
        return self._nearest_hostile(unit_id)

    def context_for(self, unit_id: str) -> BattleContext:
        """Тот же бой глазами актёра: src, его per-token оружие и скорость (WP2).

        Цель пересобирается С ЛИЦА АКТЁРА (_default_target_for), чтобы признак isTargeted был
        симметричен для обеих команд; путь героя (BC/serving/parity) остаётся с клиентской целью.
        """
        raw = self._raw()
        target = self._default_target_for(unit_id)
        weapons, speed = actor_gear(raw, unit_id, self.base.weapons, self.base.speed_steps)
        return BattleContext(scene=self.base.scene, tokens=tuple(parse_tokens({"npcs": raw["npcs"]})),
                             walls=self.base.walls, src_id=unit_id, target_id=target, raw=raw,
                             speed_steps=speed, weapons=weapons)

    @property
    def pf(self):
        """Один PathfindingService на состояние: npc_rects пекутся в __init__ quin."""
        if self._pf is None:
            self._pf = PathfindingService(self.context_for(self.hero_id))._finder
        return self._pf

    @property
    def sight(self):
        """Стены обзора один раз на состояние: позиция меняется, стены — нет (base.walls)."""
        if self._sight is None:
            self._sight = sight_segments(self.base)
        return self._sight

    def apply_hero(self, actions: List[Action]) -> "Simulation":
        """Ход героя (частный случай apply_actor для src) — контракт одиночного актёра."""
        return self.apply_actor(self.hero_id, actions)

    def apply_actor(self, actor_id: str, actions: List[Action]) -> "Simulation":
        """Актёр actor_id сходил: движение + удары по врагам ЕГО команды. Мёртвый выпадет из foes."""
        t = tuning()
        actor = self.units[actor_id]
        dirs = [a.conf.get("direction") for a in actions if a.action == ACTION_MOVE]
        cell = apply_moves(actor.cell, [d for d in dirs if d in DIR_VECTORS])
        units = {**self.units, actor_id: replace(actor, cell=cell)}
        aimed = next((a.conf.get("id") for a in reversed(actions) if a.action == ACTION_TARGET),
                     self._default_target_for(actor_id))
        for a in (x for x in actions if x.action == ACTION_USE):
            weapon = self.context_for(actor_id).weapon(a.conf.get("itemId", ""))
            foe = units.get(aimed or "")
            reach = weapon.doubt_cells if weapon else t.default_enemy_reach_cells
            if foe is None or not foe.is_alive or not are_hostile(actor, foe, self.hero_id) \
                    or not striking_distance(self.base, cell, foe.cell, reach, self.sight):
                continue        # не достать (дистанция/LOS) или свой: ход состоялся, урона нет
            # своего КД у актёра в данных нет (долг) — попадание по общему правилу
            damage = (weapon.expected_damage if weapon else t.unknown_damage_avg) * t.hit_chance
            units[aimed] = replace(foe, hp=foe.hp - damage)
        return self._clone(units)

    def apply_actor_seq(self, actor_id: str, actions: List[Action]) -> "Simulation":
        """SCHEMA=3 (F-B): действия исполняются СТРОГО по порядку.

        В отличие от apply_actor (все перемещения сворачиваются в конечную клетку, и удар
        считается из неё), здесь MOVE сдвигает текущую клетку, а USE резолвится из клетки,
        где актёр находится В МОМЕНТ удара. Это делает выразимой последовательность
        «атаковать с исходной позиции -> отступить» и «выйти из укрытия -> выстрелить ->
        вернуться»: удар проверяется по позиции атаки, а не по финальной позиции.
        Урон — ожиданием (как apply_actor); доступность удара (дистанция + линия видимости из
        позиции удара) задаёт единое правило planner/los.striking_distance (F-C).
        """
        t = tuning()
        actor = self.units[actor_id]
        cell = actor.cell
        units = {**self.units}
        aimed = self._default_target_for(actor_id)
        for a in actions:
            if a.action == ACTION_MOVE:
                d = a.conf.get("direction")
                if d in DIR_VECTORS:
                    cell = apply_moves(cell, [d])
                    units[actor_id] = replace(units[actor_id], cell=cell)
            elif a.action == ACTION_TARGET:
                aimed = a.conf.get("id")
            elif a.action == ACTION_USE:
                weapon = self.context_for(actor_id).weapon(a.conf.get("itemId", ""))
                foe = units.get(aimed or "")
                reach = weapon.doubt_cells if weapon else t.default_enemy_reach_cells
                if foe is None or not foe.is_alive or not are_hostile(actor, foe, self.hero_id) \
                        or not striking_distance(self.base, cell, foe.cell, reach, self.sight):
                    continue        # удар из ТЕКУЩЕЙ клетки: дистанция/LOS/свой — урона нет
                damage = (weapon.expected_damage if weapon else t.unknown_damage_avg) * t.hit_chance
                units[aimed] = replace(foe, hp=foe.hp - damage)
        return self._clone(units)

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
            if not striking_distance(self.base, unit.cell, hero.cell, unit.reach_cells, self.sight):
                unit = self._approach(unit, hero.cell)
                units[unit.id] = unit
            hero = units[self.hero_id]
            if striking_distance(self.base, unit.cell, hero.cell, unit.reach_cells, self.sight):
                penalty += t.damage_penalty * unit.chance      # штраф за сам факт урона
                units[self.hero_id] = replace(hero, hp=hero.hp - unit.damage_avg * unit.chance)
        dead = not units[self.hero_id].is_alive
        return (self._clone(units, dead), penalty + (t.death_penalty if dead else 0.0))

    def advance(self, actions: List[Action]) -> Tuple["Simulation", float]:
        """Прогон раунда: значение = очки плана глазами Scorer + ответ врагов."""
        state, penalty = self.apply_hero(actions).foes_act()
        return state, Scorer().score(self.context_for(self.hero_id), actions) + penalty

    def advance_seq(self, actions: List[Action]) -> Tuple["Simulation", float]:
        """Значение раунда при ПОРЯДКОВОМ исполнении (SCHEMA=3, ЭТАП 6, часть 1.3).

        Отличие от advance: переход состояния считает apply_actor_seq (удар резолвится из
        клетки атаки, а не из финальной), поэтому для плана «атака -> отход» значение точное.
        Для v2-плана (все MOVE перед USE) это то же число: клетка в момент удара совпадает с
        финальной. Очки Scorer (прицел/сближение) и ответ врагов (foes_act по финальной клетке)
        считаются как в advance — меняем лишь способ применения запланированной последовательности.
        """
        state, penalty = self.apply_actor_seq(self.hero_id, actions).foes_act()
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
