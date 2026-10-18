# planner/scoring.py — очки стратегий хода (пункт 4 todo.md).
#
# Правила из плана:
#  • сближение: 1 очко за каждые 5 футов вдоль прямой до ОПОРНОГО врага — цели
#    атаки, если атака в плане есть, иначе ближайшего врага (иначе подход к своей
#    цели не стоил бы очков, пока рядом стоит кто-то другой);
#  • атака: 30 очков за уверенное попадание, 15 — за сомнительную (дальняя
#    дистанция оружия); вне обеих зон атака очков не даёт;
#  • пункт 5 добавит штраф за полученный урон и многораундовый lookahead.
from typing import List, Optional

from planner.action import ACTION_MOVE, ACTION_TARGET, ACTION_USE, Action
from planner.armament import DOUBT, SURE
from planner.context import BattleContext
from planner.geometry import (
    DIR_VECTORS, FEET_PER_CELL, apply_moves, cell_distance,
)

MOVE_POINT_PER_CELL = 1      # очко за каждую клетку (5 футов) сближения
ATTACK_POINT = 30            # очко за уверенную атаку
ATTACK_DOUBT_POINT = 15      # очко за сомнительную атаку (на длинной дистанции)
DAMAGE_PENALTY = -30         # штраф за получение урона (пункт 5)
PLAN_TIME_LIMIT_SEC = 5.0    # лимит времени на перебор (пункт 4)


class Scorer:
    """Суммарные очки последовательности действий относительно опорного врага."""

    def score(self, context: BattleContext, actions: List[Action]) -> float:
        b = self.breakdown(context, actions)
        return b["approach"] + b["sure"] * ATTACK_POINT + b["doubt"] * ATTACK_DOUBT_POINT

    def breakdown(self, context: BattleContext, actions: List[Action]) -> dict:
        """Составляющие оценки: прямая до опорного врага до/после, очки сближения, атаки.

        ref_kind/ref_id/ref_name/weapon_name — диагностика для логов: относительно
        кого мерилось сближение и чем (и в кого) били.
        """
        enemies = context.hostile_targets()
        if not enemies:
            return {"before": 0.0, "after": 0.0, "approach": 0.0, "sure": 0, "doubt": 0,
                    "attacks": 0, "attack_points": 0.0,
                    "ref_kind": "", "ref_id": "", "ref_name": "", "weapon_name": ""}

        start = context.src_cell
        directions, uses = [], []
        for a in actions:
            if a.action == ACTION_MOVE:
                d = a.conf.get("direction")
                if d in DIR_VECTORS:
                    directions.append(d)
            elif a.action == ACTION_USE:
                uses.append(a)
        end = apply_moves(start, directions)

        target = self._targeted(context, actions, enemies) if uses else None
        ref = target if target is not None else min(
            enemies, key=lambda e: cell_distance(start, context.cell_of(e)))
        before = cell_distance(start, context.cell_of(ref))
        after = cell_distance(end, context.cell_of(ref))
        approach = (before - after) * MOVE_POINT_PER_CELL

        sure = doubt = 0
        weapon_name = ""
        if uses:
            for a in uses:
                mode = self._mode(context, end, a, target)
                if mode == SURE:
                    sure += 1
                elif mode == DOUBT:
                    doubt += 1
            weapon = context.weapon(uses[0].conf.get("itemId", ""))
            weapon_name = weapon.name if weapon else ""
        attack_points = sure * ATTACK_POINT + doubt * ATTACK_DOUBT_POINT
        return {"before": before, "after": after, "approach": approach, "sure": sure,
                "doubt": doubt, "attacks": sure + doubt, "attack_points": attack_points,
                "ref_kind": "target" if target is not None else "nearest",
                "ref_id": ref.id, "ref_name": ref.name, "weapon_name": weapon_name}

    @staticmethod
    def _mode(context: BattleContext, end, action: Action, target) -> Optional[str]:
        """Зона попадания атаки из клетки end в target; неизвестное оружие — уверенно."""
        weapon = context.weapon(action.conf.get("itemId", ""))
        if weapon is None:
            return SURE          # обратная совместимость: атака без описания оружия
        return weapon.mode_at(cell_distance(end, context.cell_of(target)))

    @staticmethod
    def _targeted(context: BattleContext, actions: List[Action], enemies):
        """Враг, на который указывает последнее target-действие (иначе — ближайший)."""
        targeted = next((a.conf.get("id") for a in reversed(actions)
                         if a.action == ACTION_TARGET), None)
        token = context.token(targeted) if targeted else None
        return token if token in enemies else min(
            enemies, key=lambda e: cell_distance(context.src_cell, context.cell_of(e)))

    def explain(self, context: BattleContext, actions: List[Action]) -> str:
        """Мини-отчёт «за что начислены очки» (расстояния в футах); пусто, если врагов нет."""
        if not context.hostile_targets():
            return ""
        b = self.breakdown(context, actions)
        zones = ", ".join(filter(None, [
            f"{b['sure']} уверенная (+{b['sure'] * ATTACK_POINT:g})" if b["sure"] else "",
            f"{b['doubt']} сомнительная (+{b['doubt'] * ATTACK_DOUBT_POINT:g})" if b["doubt"] else "",
        ])) or f"нет ({b['attack_points']:+g})"
        ref_label = "к цели" if b["ref_kind"] == "target" else "к ближайшему"
        text = (f"сближение {b['before'] * FEET_PER_CELL:g}→{b['after'] * FEET_PER_CELL:g} футов "
                f"({b['approach']:+g}) {ref_label}, "
                f"атак: {b['attacks']} ({zones})")
        if b["attacks"]:
            # имя в арене повторяется («Стражник (1)» ×5), поэтому рядом всегда id
            who = f"«{b['ref_name']}» {b['ref_id']}" if b["ref_name"] else b["ref_id"]
            text += f": {b['weapon_name'] or 'атака'} → {who}"
        return text
