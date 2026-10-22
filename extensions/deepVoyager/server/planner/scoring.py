# planner/scoring.py — очки стратегий хода (пункт 4 todo.md).
#
# Правила:
#  • сближение: очко за каждые 5 футов (actions.move.pointsPerCell) вдоль прямой до
#    ОПОРНОГО врага — цели атаки, если атака в плане есть, иначе ближайшего врага
#    (иначе подход к своей цели не стоил бы очков, пока рядом стоит кто-то другой);
#  • атака: actions.attack.sure за уверенное попадание, actions.attack.doubt — за
#    сомнительную (дальняя дистанция оружия); вне обеих зон атака очков не даёт;
#  • пункт 5 добавит штраф за полученный урон (actions.damageTaken.points) и
#    многораундовый lookahead.
# Все числа — из points.json (planner/points.py), в этом файле их нет.
from typing import List, Optional

from planner.action import ACTION_MOVE, ACTION_TARGET, ACTION_USE, Action
from planner.armament import DOUBT, SURE
from planner.context import BattleContext
from planner.geometry import DIR_VECTORS, apply_moves, cell_distance
from planner.los import los_clear
from planner.points import tuning


class Scorer:
    """Суммарные очки последовательности действий относительно опорного врага."""

    def score(self, context: BattleContext, actions: List[Action]) -> float:
        b = self.breakdown(context, actions)
        t = tuning()
        return b["approach"] + b["sure"] * t.attack_sure + b["doubt"] * t.attack_doubt

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

        t = tuning()
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
        approach = (before - after) * t.move_per_cell

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
        attack_points = sure * t.attack_sure + doubt * t.attack_doubt
        return {"before": before, "after": after, "approach": approach, "sure": sure,
                "doubt": doubt, "attacks": sure + doubt, "attack_points": attack_points,
                "ref_kind": "target" if target is not None else "nearest",
                "ref_id": ref.id, "ref_name": ref.name, "weapon_name": weapon_name}

    @staticmethod
    def _mode(context: BattleContext, end, action: Action, target) -> Optional[str]:
        """Зона попадания атаки из клетки end в target; неизвестное оружие — уверенно.

        F-C: атака засчитывается только при линии видимости из клетки удара — тот же
        критерий, что у sim.striking_distance. Без LOS атака очков не даёт (иначе
        планировщик ценил бы удар сквозь стену, который симуляция обнуляет).
        """
        weapon = context.weapon(action.conf.get("itemId", ""))
        if not los_clear(context, end, context.cell_of(target)):
            return None
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
        t = tuning()
        b = self.breakdown(context, actions)
        zones = ", ".join(filter(None, [
            f"{b['sure']} уверенная (+{b['sure'] * t.attack_sure:g})" if b["sure"] else "",
            f"{b['doubt']} сомнительная (+{b['doubt'] * t.attack_doubt:g})" if b["doubt"] else "",
        ])) or f"нет ({b['attack_points']:+g})"
        ref_label = "к цели" if b["ref_kind"] == "target" else "к ближайшему"
        text = (f"сближение {b['before'] * t.feet_per_cell:g}→{b['after'] * t.feet_per_cell:g} "
                f"футов ({b['approach']:+g}) {ref_label}, "
                f"атак: {b['attacks']} ({zones})")
        if b["attacks"]:
            # имя в арене повторяется («Стражник (1)» ×5), поэтому рядом всегда id
            who = f"«{b['ref_name']}» {b['ref_id']}" if b["ref_name"] else b["ref_id"]
            text += f": {b['weapon_name'] or 'атака'} → {who}"
        return text
