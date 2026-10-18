# planner/scoring.py — очки стратегий хода (пункт 4 todo.md).
#
# Правила из плана:
#  • сближение: расстояние по прямой до ближайшей цели, 1 очко за каждые 5 футов;
#  • атака: 30 очков за каждое действие use;
#  • пункт 5 добавит штраф за полученный урон и многораундовый lookahead.
from typing import List

from planner.action import ACTION_MOVE, ACTION_USE, Action
from planner.context import BattleContext
from planner.geometry import DIR_VECTORS, FEET_PER_CELL, apply_moves, cell_distance

MOVE_POINT_PER_CELL = 1      # очко за каждую клетку (5 футов) сближения
ATTACK_POINT = 30            # очко за каждую атаку
DAMAGE_PENALTY = -30         # штраф за получение урона (пункт 5)
PLAN_TIME_LIMIT_SEC = 5.0    # лимит времени на перебор (пункт 4)


class Scorer:
    """Суммарные очки последовательности действий относительно ближайшего врага."""

    def score(self, context: BattleContext, actions: List[Action]) -> float:
        b = self.breakdown(context, actions)
        return b["approach"] + b["attacks"] * ATTACK_POINT

    def breakdown(self, context: BattleContext, actions: List[Action]) -> dict:
        """Составляющие оценки: прямая до цели до/после шага, очки сближения, число атак."""
        enemies = context.hostile_targets()
        if not enemies:
            return {"before": 0.0, "after": 0.0, "approach": 0.0, "attacks": 0}

        start = context.src_cell
        directions, attacks = [], 0
        for a in actions:
            if a.action == ACTION_MOVE:
                d = a.conf.get("direction")
                if d in DIR_VECTORS:
                    directions.append(d)
            elif a.action == ACTION_USE:
                attacks += 1
        end = apply_moves(start, directions)

        before = min(cell_distance(start, context.cell_of(e)) for e in enemies)
        after = min(cell_distance(end, context.cell_of(e)) for e in enemies)
        approach = (before - after) * MOVE_POINT_PER_CELL
        return {"before": before, "after": after, "approach": approach, "attacks": attacks}

    def explain(self, context: BattleContext, actions: List[Action]) -> str:
        """Мини-отчёт «за что начислены очки» (расстояния в футах); пусто, если врагов нет."""
        if not context.hostile_targets():
            return ""
        b = self.breakdown(context, actions)
        return (f"сближение {b['before'] * FEET_PER_CELL:g}→{b['after'] * FEET_PER_CELL:g} футов "
                f"({b['approach']:+g}), "
                f"атак: {b['attacks']} ({b['attacks'] * ATTACK_POINT:+g})")
