# arent/ext_teachers.py — внешние политики-учителя для бенчмарка (Фаза A / A1).
#
# Каждая — НАШ battlecast с иным профилем весов, подключается РЕЕСТРОМ (@register), поэтому
# доступен везде без правок боевого контура: демо BC (dataset.generate teacher=...), оппонент
# PPO (RlConfig.duel_opponents), соперник гейта, closed-loop A/B (team_eval.build_controller
# уже оборачивает имя в TeacherController). Реестр -> имя -> политика, ядра боя не тронуты.
#
# ЧЕСТНО про лицензию (см. search_teacher/PHASE0.md): у UFO / Wesnoth / JA2 copyleft или
# неподтверждённый статус, поэтому СЮДА НЕ перенесён их код — только переопределённые веса
# EV нашей же политики под тактическую ИДЕЮ стиля. Настоящие evaluate_plan (позиция+атака+
# укрытие одним планом, UFO) и team focus-fire (командная оценка целей, Wesnoth) появятся в
# Фазах B/C как НОВОЕ поведение, а не как переименование battlecast с другими числами.
#
# Состав Фазы A (минимум для бенчмарка):
#  • battlecast_baseline — честный алиас battlecast (неизменная базовая колонка A/B).
#  • ja2_positioning      — осторожный позиционный профиль: сильнее штрафует входящий огонь
#    и ценит Отступление/Уклонение (идея JA2, без кода). Остальные стили добавляются в B/C.
from typing import Any, Dict, Optional

from planner.context import BattleContext
from planner.explore import reachable_paths
from planner.geometry import cell_distance
from planner.los import has_los, sight_segments
from planner.pathfinding import PathfindingService
from planner.points import tuning

from arent.battlecast import BattlecastTeacher
from arent.battlecast_heuristics import best_strike, incoming_at_cell, position_value
from arent.battlecast_v2 import BattlecastV2Teacher
from arent.tactics_config import ManeuverWeights
from arent.teachers import register


@register("battlecast_baseline")
class BattlecastBaseline(BattlecastTeacher):
    """Базовая колонка бенчмарка: идентичен battlecast (проверено тестом равенства метки)."""


@register("ja2_positioning")
class Ja2Positioning(BattlecastTeacher):
    """Осторожный позиционный стиль (идея JA2, без кода): держит позицию с меньшей угрозой.

    threat>1 усиливает штраф за входящий огонь при выборе клетки; повышенные веса
    Disengage/Dodge сдвигают выбор в сторону «отойти/укрыться», когда удар не перебивает.
    """

    def __init__(self, rounds: int = 1, time_limit_sec: Optional[float] = None,
                 value_rounds: Optional[int] = None, threat: float = 1.6,
                 maneuver_weights: Optional[ManeuverWeights] = None):
        mw = maneuver_weights if maneuver_weights is not None else ManeuverWeights(
            dash_bonus=0.5, disengage_bonus=2.0, dodge_bonus=1.5)
        super().__init__(rounds=rounds, time_limit_sec=time_limit_sec,
                         value_rounds=value_rounds, threat=threat, maneuver_weights=mw)


# ─── Фаза C: поведенчески ОТЛИЧНЫЕ стили (не перевес весов, а иной способ/функция ценности)

@register("ufo_style")
class UFOStyleTeacher(BattlecastV2Teacher):
    """Агрессивный стиль «развязка ПОЛНОГО плана по исходу» (идея XCOM/UFO, без их кода).

    Отличие от базы — НЕ вес, а механизм: выбор делается оценкой исхода НАШЕЙ симуляции
    (rollout) над всем набором кандидатов (атака по клеткам + манёвры), а не линейной EV.
    Агрессивный профиль (threat<1) толерантнее к входящему огню — стиль идёт добивать,
    приняв ответку, тогда как ja2_positioning (threat>1) от неё шарахается. Код UFO не
    переносился (copyleft): переиспользован только НАШ механизм battlecast_v2.
    """

    def __init__(self, rounds: int = 1, time_limit_sec: Optional[float] = None,
                 value_rounds: Optional[int] = None, threat: float = 0.7,
                 maneuver_weights: Optional[ManeuverWeights] = None,
                 horizon: int = 2, top: int = 6, margin: float = 0.0):
        super().__init__(rounds=rounds, time_limit_sec=time_limit_sec,
                         value_rounds=value_rounds, threat=threat,
                         maneuver_weights=maneuver_weights,
                         horizon=horizon, top=top, margin=margin)


@register("cdda_ranged_support")
class CddaRangedSupport(BattlecastTeacher):
    """Скирмишер-поддержка (идея CDDA ranged keep-away): НОВЫЙ член функции ценности.

    choose() базы сворачивает клетку в EV-удар − угроза. Здесь к той же свёртке добавляется
    слагаемая ``keep_distance * (дистанция до ближайшего врага)`` — дальник сознательно
    разворачивает бой на дистанции, даже когда входящий огонь уже равен нулю (то есть
    штраф угрозы тут не при чём: это отдельная цель «держать интервал», а не перевес threat).
    Якорь: keep_distance=0 сводит choose() к ровно базовому (проверено тестом).
    """

    def __init__(self, rounds: int = 1, time_limit_sec: Optional[float] = None,
                 value_rounds: Optional[int] = None, threat: Optional[float] = None,
                 maneuver_weights: Optional[ManeuverWeights] = None,
                 keep_distance: float = 1.5):
        super().__init__(rounds=rounds, time_limit_sec=time_limit_sec,
                         value_rounds=value_rounds, threat=threat,
                         maneuver_weights=maneuver_weights)
        self.keep_distance = float(keep_distance)

    def choose(self, ctx: BattleContext, obs: Dict[str, Any]):
        """(value, cell, dirs, target, weapon, has_strike) — как у базы, плюс член дистанции.

        Формула/детерминизм/легальность полностью повторяют BattlecastTeacher.choose, чтобы
        keep_distance=0 дал ПОБИТОВО базу; отличие вносит ровно одна строка (keep ниже).
        """
        enemies = self._enemies(ctx, obs)
        weapons = list(ctx.weapons)
        fallback = tuning().hit_chance
        me_cell = ctx.src_cell
        pf = PathfindingService(ctx)._finder
        paths = reachable_paths(pf, me_cell, ctx.src_id, ctx.speed_steps)
        segments = sight_segments(ctx)
        los = lambda a, b: has_los(ctx, a, b, segments)   # noqa: E731
        best = None
        for cell, dirs in sorted(paths.items(), key=lambda kv: (len(kv[1]), kv[0])):
            strike = best_strike(cell, enemies, weapons, fallback, los=los)
            if strike is not None:
                target, weapon, ev = strike
                approach = 0.0
            else:
                target, weapon, ev = self._nearest(cell, enemies), None, 0.0
                approach = cell_distance(me_cell, target.cell) - cell_distance(cell, target.cell)
            value = position_value(ev, approach, incoming_at_cell(cell, enemies) * self.threat)
            # --- новый член ценности: скирмишер ценит интервал до ближайшего врага (kiting) ---
            keep = min((cell_distance(cell, e.cell) for e in enemies), default=0.0)
            value += self.keep_distance * keep
            if best is None or value > best[0]:
                best = (value, cell, dirs, target, weapon, strike is not None)
        return best
