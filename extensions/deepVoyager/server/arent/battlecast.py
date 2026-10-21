# arent/battlecast.py — учитель-политика на портированных эвристиках battlecast (MIT).
#
# Структура решения взята из battlecast-engine (см. battlecast_LICENSE.txt), но исполняется
# на НАШИХ примитивах: клетки-кандидаты даёт наш BFS (planner.explore.reachable_paths с
# правилами стен/углов/занятости), легальность атаки — наши зоны (weapon.mode_at), значение
# линии — наш Simulation.rollout. Чужой pathfinder не используется и не подмешивается.
#
# Отличие от greedy: цель и позиция выбираются по ожидаемому урону и приоритету добить,
# позиция дополнительно штрафуется за реальный EV ответного огня. Всё решается за один ход
# (rounds не углубляет дерево — это однопроходная политика), поэтому разметка дешёвая.
from typing import Any, Dict, List, Optional

from planner.action import move_action, target_action, use_action
from planner.context import BattleContext
from planner.explore import reachable_paths
from planner.geometry import cell_distance
from planner.pathfinding import PathfindingService
from planner.points import tuning
from planner.scoring import Scorer
from planner.turns import rollout
from arent.battlecast_heuristics import Enemy, best_strike, incoming_at_cell, position_value
from arent.observe import observe
from arent.teacher import Labeled
from arent.teachers import TeacherPolicy, register


@register("battlecast")
class BattlecastTeacher(TeacherPolicy):
    """Тактическая политика: EV-выбор цели + приоритет добить + угроза-взвешенная позиция."""

    def __init__(self, rounds: int = 1, time_limit_sec: Optional[float] = None,
                 value_rounds: Optional[int] = None):
        # rounds/time_limit_sec приняты для совместимости с реестром: политика однопроходная,
        # глубина учителя здесь не используется (в отличие от greedy/PlannerService).
        self.rounds = max(1, int(rounds))
        self.time_limit_sec = time_limit_sec
        self.value_rounds = max(1, int(value_rounds if value_rounds is not None else rounds))

    def _enemies(self, ctx: BattleContext, obs: Dict[str, Any]) -> List[Enemy]:
        """Враги для эвристик: клетка из ctx, КД/EV ответного огня из нашего наблюдения."""
        by_id = {e["id"]: e for e in obs["enemies"]}
        out = []
        for tok in ctx.hostile_targets():
            o = by_id.get(tok.id, {})
            out.append(Enemy(
                id=tok.id, cell=ctx.cell_of(tok), hp=float(tok.hp_current),
                ac=float(o.get("ac", 0.0)), dmg_to_me=float(o.get("dmgToMe", 0.0)),
                reach_cells=float(o.get("reachCells", tuning().default_enemy_reach_cells)),
                speed_cells=float(o.get("speedCells", tok.sim_speed_steps)),
            ))
        return out

    def _nearest(self, cell, enemies: List[Enemy]) -> Enemy:
        return min(enemies, key=lambda e: (cell_distance(cell, e.cell), e.cell))

    def choose(self, ctx: BattleContext, obs: Dict[str, Any]):
        """(клетка, пути, цель, оружие, EV) — лучшая клетка по портированной оценке.

        Порядок детерминирован (сначала короткие пути, затем координаты) и замена строгая,
        поэтому при равных значениях побеждает первый достигнутый оптимум — как у greedy.
        """
        enemies = self._enemies(ctx, obs)
        weapons = list(ctx.weapons)
        fallback = tuning().hit_chance
        me_cell = ctx.src_cell
        pf = PathfindingService(ctx)._finder
        paths = reachable_paths(pf, me_cell, ctx.src_id, ctx.speed_steps)
        best = None
        for cell, dirs in sorted(paths.items(), key=lambda kv: (len(kv[1]), kv[0])):
            strike = best_strike(cell, enemies, weapons, fallback)
            if strike is not None:
                target, weapon, ev = strike
                approach = 0.0
            else:
                target, weapon, ev = self._nearest(cell, enemies), None, 0.0
                engaged = target.cell
                approach = cell_distance(me_cell, engaged) - cell_distance(cell, engaged)
            value = position_value(ev, approach, incoming_at_cell(cell, enemies))
            if best is None or value > best[0]:
                best = (value, cell, dirs, target, weapon, strike is not None)
        return best

    def _actions(self, ctx: BattleContext, obs: Dict[str, Any]):
        """Список действий лучшего хода политики (пусто, если играть нечем/некуда).

        Одна и та же сборка служит и label (генерация датасета), и plan (closed-loop),
        поэтому сравнение мерит ровно тот выбор, что пойдёт в разметку.
        """
        if not ctx.weapons or not ctx.hostile_targets():
            return []
        chosen = self.choose(ctx, obs)
        if chosen is None:
            return []
        _value, _cell, dirs, target, weapon, has_strike = chosen
        actions = [target_action(target.id)] + [move_action(d) for d in dirs]
        if has_strike:
            actions.append(use_action(weapon.id))
        return actions

    def plan(self, ctx: BattleContext):
        """Действия по готовому контексту — для closed-loop сравнения на нашей симуляции."""
        return self._actions(ctx, observe(ctx))

    def label(self, payload: Dict[str, Any]) -> Labeled:
        """payload -> план battlecast-политики; value — на шкале НАШЕЙ симуляции (rollout)."""
        ctx = BattleContext.from_payload(payload)
        actions = self._actions(ctx, observe(ctx))
        # Значение — общей шкалой (rollout), а не внутренней суммой эвристик battlecast.
        value = rollout(ctx, actions, self.value_rounds)
        return Labeled(ctx=ctx, actions=actions, value=value,
                       score=Scorer().score(ctx, actions), depth=1)
