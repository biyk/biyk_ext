# arent/teacher.py — учитель разметки: существующий планировщик, а не вторая модель.
#
# Разметку даёт PlannerService (тот же код, что отвечает на /plan), значение линии —
# Simulation.rollout. Глубину lookahead учителя можно понизить на время генерации
# выборки: rounds=1 — greedy за миллисекунды, rounds=3 — тот же план, что в бою,
# но секунды на каждое состояние.
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterator, List, Optional

from planner.action import ACTION_MOVE, ACTION_USE, Action, move_action
from planner.context import BattleContext
from planner.explore import BruteForceExplorer, reachable_paths
from planner.geometry import apply_moves
from planner.pathfinding import PathfindingService
from planner.points import set_tuning, tuning
from planner.scoring import Scorer
from planner.service import PlannerService, PlanResult
from planner.sim import Simulation
from planner.turns import rollout
from planner.strategy import StrategyEnumerator
from arent.teachers import TeacherPolicy, register


@contextmanager
def pinned(rounds: Optional[int] = None, time_limit_sec: Optional[float] = None,
           shallow_k: Optional[int] = None, top_k: Optional[int] = None) -> Iterator[None]:
    """Временно зафиксировать коэффициенты планировщика и вернуть их назад.

    Нужно, чтобы выборка была воспроизводимой: points.json может лежать любой,
    а разметка учителя должна зависеть от аргументов генерации, а не от файла на диске.
    shallow_k/top_k дополнительно урезают ширину симуляции: hero_options() с 48 ходами
    на каждый раунд — это секунды на состояние, с 4 — десятки миллисекунд.
    """
    previous = tuning()
    values = replace(previous, max_rounds=max(1, rounds or 1),
                     plan_time_limit_sec=(previous.plan_time_limit_sec
                                          if time_limit_sec is None else time_limit_sec),
                     shallow_k=max(1, shallow_k) if shallow_k else previous.shallow_k,
                     top_k=max(1, top_k) if top_k else previous.top_k)
    set_tuning(values)
    try:
        yield
    finally:
        set_tuning(previous)


@dataclass
class Labeled:
    """Размеченное состояние: контекст, план учителя и его значение (шкала очков планировщика).

    actions     — ход учителя «как задуман»: для greedy-политики включает уход после удара
                  (частичка 3 ЭТАПА 5 — схема v3 умеет его исполнить через dirs_out);
    base_actions — тот же ход БЕЗ пост-атаки: подход-затем-удар в одной клетке. Схема v2
                  (клетка+атака, attack_cell==end_cell) физически не выражает уход после
                  удара, поэтому sample_one размечает именно base_actions — иначе roundtrip
                  в v2 не сходится (хвостовые MOVE после USE v2-декодер собрать не может).
    """
    ctx: BattleContext
    actions: List[Action]
    value: float
    score: float
    depth: int
    base_actions: Optional[List[Action]] = None

    def __post_init__(self):
        if self.base_actions is None:
            self.base_actions = self.actions


@register("greedy")
class Teacher(TeacherPolicy):
    """Планировщик в режиме учителя (политика по умолчанию, имя в реестре — greedy).

    rounds=1 — детерминированный перебор (quin-маршруты + все достижимые клетки) без
    случайных прогулок и без дедлайна: разметка воспроизводима и считается за миллисекунды.
    rounds>1 — тот же PlannerService, что отвечает на /plan, с lookahead: медленнее в
    сотни раз, но это ровно боковое поведение, поэтому его включают осознанно.
    """

    def __init__(self, rounds: int = 1, time_limit_sec: Optional[float] = None,
                 value_rounds: Optional[int] = None):
        self.rounds = max(1, int(rounds))
        self.time_limit_sec = time_limit_sec
        self.value_rounds = max(1, int(value_rounds if value_rounds is not None else rounds))

    def _greedy_best(self, ctx: BattleContext) -> Optional[PlanResult]:
        """Лучший кандидат перебора (с уходом после удара) — только результат, без базы."""
        return self._greedy_pair(ctx)[0]

    def _greedy_pair(self, ctx: BattleContext):
        """Возвращает (результат-с-уходом, базовые-действия-без-ухода).

        Ход-кандидат (цель/оружие/клетка атаки) выбирается жадно и НЕ меняется; к нему
        лишь доматывается уход после удара (_with_displace). Базовый ход (до ухода) отдаётся
        отдельно, чтобы схема v2 (sample_one) размечалась ровно тем, что она умеет исполнить.
        """
        scorer = Scorer()
        best = None
        for candidate in list(StrategyEnumerator(ctx, scorer=scorer).enumerate()) \
                + list(BruteForceExplorer(ctx, scorer=scorer).enumerate()):
            if best is None or candidate.score > best.score:
                best = candidate
        if best is None:
            return None, []
        base = list(best.actions)
        actions = self._with_displace(ctx, base)
        result = PlanResult(actions=actions, score=best.score, value=best.score,
                            considered=1, details="teacher=greedy")
        return result, base

    @staticmethod
    def _with_displace(ctx: BattleContext, best_actions: List[Action]) -> List[Action]:
        """Выбрать финальную клетку хода ПОСЛЕ атаки (ЭТАП 5, часть 3: «атака → перемещение»).

        Решение об ударе (цель/оружие/клетка атаки) не трогаем — берём ровно то, что выбрал
        жадный кандидат, поэтому выбор атаки не регрессирует. Перебираем только последующее
        перемещение в оставшийся бюджет (speed_steps - уже потрачено на подход) и выбираем
        позицию по УЖЕ корректно посчитанному симуляцией ответу врагов: значение штрафа берём
        из Simulation.apply_actor_seq(...).foes_act() (удар резолвится из клетки атаки, уход
        меняет лишь финальную клетку → дистанция/LOS/шанс ответки). Новых коэффициентов нет.

        Отход НЕ обязателен: вариант «остаться» (пустой dirs_out) сравнивается с уходом и
        выигрывает при равенстве — если более безопасной позиции нет, остаёмся; иногда верно и
        сблизиться (клетка атаки уже выбрана жадно). Возвращаем исходные действия, если бюджета
        или атаки нет.
        """
        uses = [a for a in best_actions if a.action == ACTION_USE]
        if not uses:
            return best_actions
        dirs_in = [a.conf.get("direction") for a in best_actions
                   if a.action == ACTION_MOVE and a.conf.get("direction")]
        leftover = ctx.speed_steps - len(dirs_in)
        if leftover <= 0:
            return best_actions
        attack_cell = apply_moves(ctx.src_cell, dirs_in)
        pf = PathfindingService(ctx)._finder
        paths = reachable_paths(pf, attack_cell, ctx.src_id, leftover)
        base = Simulation.of(ctx)
        # базовый вариант — остаться на клетке атаки (пустой уход)
        best_dirs: List[str] = []
        best_pen = base.apply_actor_seq(ctx.src_id, best_actions).foes_act()[1]
        # детерминированный порядок: сначала короткая дистанция ухода, затем координаты клетки
        options = sorted(((c, d) for c, d in paths.items() if d),
                         key=lambda kv: (len(kv[1]), kv[0]))[:40]
        for _cell, dirs_out in options:
            pen = base.apply_actor_seq(
                ctx.src_id, best_actions + [move_action(d) for d in dirs_out]).foes_act()[1]
            if pen > best_pen + 1e-9:          # строго безопаснее — иначе остаёмся на месте
                best_pen, best_dirs = pen, dirs_out
        if not best_dirs:
            return best_actions
        return best_actions + [move_action(d) for d in best_dirs]

    def label(self, payload: Dict[str, Any]) -> Labeled:
        """payload -> состояние + лучший план учителя + значение его линии (rollout)."""
        ctx = BattleContext.from_payload(payload)
        if self.rounds > 1:
            result = PlannerService(time_limit_sec=self.time_limit_sec).plan_result(ctx)
            base = list(result.actions)          # PlannerService не добавляет уход после удара
        else:
            result, base = self._greedy_pair(ctx)
            result = result or PlanResult()
        value = result.value if result.depth > 1 else rollout(ctx, result.actions, self.value_rounds)
        return Labeled(ctx=ctx, actions=result.actions, value=value,
                       score=result.score, depth=result.depth, base_actions=base)

    def plan(self, ctx: BattleContext) -> List[Action]:
        """Тот же выбор, что label, но по готовому контексту — для closed-loop сравнения."""
        if self.rounds > 1:
            return PlannerService(time_limit_sec=self.time_limit_sec).plan_result(ctx).actions
        return (self._greedy_best(ctx) or PlanResult()).actions
