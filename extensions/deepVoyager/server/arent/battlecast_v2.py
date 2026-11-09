# arent/battlecast_v2.py — Фаза B: усиленный battlecast как НАДСТРОЙКА над базовым.
#
# Идея (из внешних тактик, см. search_teacher/PLAN.md): однопроходная EV-политика базы
# выбирает клетку линейной свёрткой (урон − угроза), но не видит исхода — что мёртвый враг
# перестаёт бить, а стояние в четырёх melee-зонах складывается по урону. v2 оставляет
# РОВНО тот же набор кандидатов, что перебирает база (атака по клеткам + манёвры), но
# развязку делает по исходу НАШЕЙ симуляции (planner.turns.rollout) с guard'ом margin:
# переключаемся с базового выбора только если кандидат перебивает его строго на margin.
#
# Честность и безопасность регрессии:
#  • базовый battlecast.py НЕ тронут — v2 subclass, реестр "battlecast" не подменён;
#  • margin=+inf -> план побитово равен базовому battlecast (якорь в тестах);
#  • набор кандидатов ВКЛЮЧАЕТ линию манёвра (_dash/disengage/dodge_), а не только атаки:
#    прототип Фазы B терял Уклонение/Отступление на пуле именно потому, что рассматривал
#    одни атакующие клетки — здесь это исправлено;
#  • value остаётся на шкале rollout (наследуется label_ctx), никакой внутренней суммы.
import math
from typing import Any, Dict, List

from planner.action import move_action, target_action, use_action
from planner.context import BattleContext
from planner.explore import reachable_paths
from planner.geometry import cell_distance
from planner.los import has_los, sight_segments
from planner.pathfinding import PathfindingService
from planner.points import tuning
from planner.turns import rollout

from arent.battlecast import BattlecastTeacher
from arent.battlecast_heuristics import best_strike, incoming_at_cell, position_value
from arent.teachers import register


@register("battlecast_v2")
class BattlecastV2Teacher(BattlecastTeacher):
    """Базовый battlecast + развязка по исходу симуляции над полным набором кандидатов."""

    def __init__(self, rounds: int = 1, time_limit_sec=None, value_rounds=None,
                 threat=None, maneuver_weights=None, horizon: int = 2,
                 top: int = 6, margin: float = 0.0):
        super().__init__(rounds=rounds, time_limit_sec=time_limit_sec,
                         value_rounds=value_rounds, threat=threat,
                         maneuver_weights=maneuver_weights)
        # horizon — глубина rollout-оценки исхода при РАЗВЯЗКЕ (не путать с value_rounds:
        # тем размечаем итоговый план). top — сколько атакующих клеток-кандидатов сохраняем.
        # margin — порог переключения с базового выбора; +inf => никогда (rovно база).
        self.horizon = max(1, int(horizon))
        self.top = max(1, int(top))
        self.margin = float(margin)

    def _candidate_lines(self, ctx: BattleContext, obs: Dict[str, Any]) -> List[List[Any]]:
        """Полный набор кандидатных линий: топ-N атак по клеткам + линия каждого манёвра.

        Порядок детерминирован (сорт по длине пути/координате, как в choose), поэтому
        перебор rollout'ом даёт тот же argmax при равных значениях. Атакующие клетки
        ранжируются быстрой оценкой базы (position_value) — мы не бросаем худшие клетки
        наугад, а берём top лучших, и к ним добавляем манёвры без EV-гейта (решит исход).
        """
        enemies = self._enemies(ctx, obs)
        if not enemies:
            return []
        weapons = list(ctx.weapons)
        fallback = tuning().hit_chance
        me_cell = ctx.src_cell
        pf = PathfindingService(ctx)._finder
        normal = reachable_paths(pf, me_cell, ctx.src_id, ctx.speed_steps)
        segments = sight_segments(ctx)
        los = lambda a, b: has_los(ctx, a, b, segments)   # noqa: E731
        lines: List[List[Any]] = []

        # --- атакующие линии по достижимым клеткам (та же свёртка, что в choose) ---
        if weapons:
            scored = []
            for cell, dirs in sorted(normal.items(), key=lambda kv: (len(kv[1]), kv[0])):
                strike = best_strike(cell, enemies, weapons, fallback, los=los)
                if strike is not None:
                    target, weapon, ev = strike
                    approach = 0.0
                else:
                    target, weapon, ev = self._nearest(cell, enemies), None, 0.0
                    approach = cell_distance(me_cell, target.cell) - cell_distance(cell, target.cell)
                fast = position_value(ev, approach, incoming_at_cell(cell, enemies) * self.threat)
                actions = [target_action(target.id)] + [move_action(d) for d in dirs]
                if strike is not None:
                    actions.append(use_action(weapon.id))
                scored.append((fast, cell, actions))
            scored.sort(key=lambda s: (-s[0], s[1]))
            lines.extend(actions for _f, _c, actions in scored[:self.top])

        # --- линии манёвров: каждая доступная категория, независимо от EV-гейта базы ---
        items = self._maneuver_items(ctx)
        if items and self._action_available(obs):
            for kind in ("dodge", "disengage", "dash"):
                if kind not in items:
                    continue
                if kind == "dash":
                    dash = reachable_paths(pf, me_cell, ctx.src_id, ctx.speed_steps * 2)
                    cells = {c: p for c, p in dash.items() if c not in normal}
                    if not cells:
                        continue
                else:
                    cells = normal
                _val, dirs = self._best_move_line(cells, me_cell, enemies, 0.0,
                                                  dodge=(kind == "dodge"),
                                                  avoid=(kind == "disengage"))
                lines.append([move_action(d) for d in (dirs or [])]
                             + [use_action(items[kind]["id"])])
        return lines

    def _actions(self, ctx: BattleContext, obs: Dict[str, Any]) -> List[Any]:
        """Развязка по исходу: стартуем с базового battlecast-выбора, переключаемся лишь
        когда кандидат строит лучший rollout с запасом margin. Пустой базовый план не
        изобретается — v2 уточняет решение там, где база его уже нашла."""
        base_line = super()._actions(ctx, obs)
        if not base_line:
            return base_line
        if math.isinf(self.margin) and self.margin > 0:
            return base_line                        # якорь: никогда не переключаемся == база
        candidates = self._candidate_lines(ctx, obs)
        if not candidates:
            return base_line
        best_line = base_line
        best_val = rollout(ctx, base_line, self.horizon)
        for line in candidates:
            v = rollout(ctx, line, self.horizon)
            if v > best_val + self.margin:          # строгий запас -> tie остаётся базовый
                best_line, best_val = line, v
        return best_line
