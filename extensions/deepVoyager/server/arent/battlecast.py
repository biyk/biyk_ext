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
from planner.los import has_los, sight_segments
from planner.pathfinding import PathfindingService
from planner.points import tuning
from planner.scoring import Scorer
from planner.turns import rollout
from arent import tactics_config
from arent.battlecast_heuristics import (Enemy, avoided_opportunities, best_strike,
                                         incoming_at_cell, movement_value, position_value)
from arent.observe import observe
from arent.teacher import Labeled
from arent.teachers import TeacherPolicy, register

# Вид манёвра -> имя слота в ManeuverWeights (tactics.maneuvers.*_bonus).
_MANEUVER_WEIGHT = {"dash": "dash_bonus", "disengage": "disengage_bonus", "dodge": "dodge_bonus"}


@register("battlecast")
class BattlecastTeacher(TeacherPolicy):
    """Тактическая политика: EV-выбор цели + приоритет добить + угроза-взвешенная позиция."""

    def __init__(self, rounds: int = 1, time_limit_sec: Optional[float] = None,
                 value_rounds: Optional[int] = None, threat: Optional[float] = None,
                 maneuver_weights=None):
        # rounds/time_limit_sec приняты для совместимости с реестром: политика однопроходная,
        # глубина учителя здесь не используется (в отличие от greedy/PlannerService).
        self.rounds = max(1, int(rounds))
        self.time_limit_sec = time_limit_sec
        self.value_rounds = max(1, int(value_rounds if value_rounds is not None else rounds))
        # Профиль стиля (Фаза A): threat — множитель штрафа за входящий огонь при выборе
        # позиции; maneuver_weights — веса Dash/Disengage/Dodge. Значения по умолчанию
        # (1.0 / None -> читаем tactics_config) дают РОВНО штатный battlecast, поэтому
        # существующее поведение и чекпойнты не меняются. Профильные подклассы переопределяют.
        self.threat = 1.0 if threat is None else float(threat)
        self.maneuver_weights = maneuver_weights

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
        # F-D: выбор цели согласован с F-C — атака считается только по клеткам с линией
        # видимости (has_los из planner/los), поэтому учитель больше не «бьёт сквозь стену»,
        # которую уже видят наблюдение, маски и исполнение урона.
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
                engaged = target.cell
                approach = cell_distance(me_cell, engaged) - cell_distance(cell, engaged)
            value = position_value(ev, approach, incoming_at_cell(cell, enemies) * self.threat)
            if best is None or value > best[0]:
                best = (value, cell, dirs, target, weapon, strike is not None)
        return best

    def _actions(self, ctx: BattleContext, obs: Dict[str, Any]):
        """Список действий лучшего хода политики (пусто, если играть нечем/некуда).

        Одна и та же сборка служит и label (генерация датасета), и plan (closed-loop),
        поэтому сравнение мерит ровно тот выбор, что пойдёт в разметку. На схеме v5
        (ctx.maneuver_items непусто) политика дополнительно рассматривает Рывок/Отступление/
        Уклонение и, если манёвр перебивает удар по EV, отдаёт use_action(предмет-манёвр).
        Для v2/v3/v4 (maneuver_items пусто) — ровно прежний путь «подход-затем-удар».
        """
        if not ctx.hostile_targets():
            return []
        if not ctx.weapons and not ctx.maneuver_items:
            return []
        chosen = self.choose(ctx, obs) if ctx.weapons else None
        maneuver = self._choose_maneuver(ctx, obs, chosen)
        if maneuver is not None:
            return maneuver
        return self._attack_actions(chosen)

    def _attack_actions(self, chosen):
        """Прежние атакующие действия учителя (цель + маршруты + опциональный удар)."""
        if chosen is None:
            return []
        _value, _cell, dirs, target, weapon, has_strike = chosen
        actions = [target_action(target.id)] + [move_action(d) for d in dirs]
        if has_strike:
            actions.append(use_action(weapon.id))
        return actions

    def _maneuver_items(self, ctx: BattleContext) -> Dict[str, Dict[str, Any]]:
        """kind -> предмет-манёвр (dash/disengage/dodge). Первый на вид берётся; пустой
        реестр (v2/v3/v4 или payload без maneuvers) -> {} — манёвры не рассматриваются."""
        out: Dict[str, Dict[str, Any]] = {}
        for m in ctx.maneuver_items or ():
            kind = m.get("kind")
            if kind in _MANEUVER_WEIGHT and m.get("id") and kind not in out:
                out[kind] = m
        return out

    @staticmethod
    def _action_available(obs: Dict[str, Any]) -> bool:
        """Есть ли у актёра действие (манёвр тратит Action). Без данных — считаем доступным."""
        return float(obs.get("me", {}).get("actionRemaining", 1.0)) >= 1.0

    def _best_move_line(self, paths, me_cell, enemies, bonus, dodge, avoid):
        """(значение, направления) лучшей клетки перемещения БЕЗ удара.

        Ценность = movement_value (позиция минус угроза; dodge=True уменьшает входящий
        огонь вдвое) + при avoid — экономия провоцированных Ao на выходе из melee-зон.
        Перебор по sorted(cells) детерминирован; ties -> первая клетка по координате
        (как в choose).
        """
        best_val, best_cell = None, None
        for cell in sorted(paths):
            v = movement_value(cell, me_cell, enemies, dodge=dodge)
            if avoid:
                v += avoided_opportunities(me_cell, cell, enemies)
            if best_val is None or v > best_val:
                best_val, best_cell = v, cell
        if best_val is None:
            return float("-inf"), []
        return best_val + bonus, paths[best_cell]

    def _choose_maneuver(self, ctx: BattleContext, obs: Dict[str, Any], chosen):
        """Действия манёвра, если он перебивает удар; иначе None (idём атакой, как раньше).

        serving==train: каждое слагаемое — тот же EV-урон, что считает sim. Сравниваем линии:
         • Уклонение — позиция с половинным входящим огнём (dodge=True), часто на месте;
         • Отступление — обычный ход, покидающий melee-зоны, плюс сэкономленные Ao;
         • Рывок — только клетки, недосягаемые обычным шагом (2× бюджет), без удара.
        Побеждает максимум; манёвр берётся лишь строго перебив baseline атакующей линии.
        """
        items = self._maneuver_items(ctx)
        if not items or not self._action_available(obs):
            return None
        enemies = self._enemies(ctx, obs)
        if not enemies:
            return None
        w = self.maneuver_weights if self.maneuver_weights is not None \
            else tactics_config.config().maneuver
        me_cell = ctx.src_cell
        pf = PathfindingService(ctx)._finder
        normal = reachable_paths(pf, me_cell, ctx.src_id, ctx.speed_steps)
        # Базовая линия = лучший ХОД БЕЗ манёвра: с оружием это атакующая линия choose()
        # (в ней уже вычтен полный входящий огонь), без оружия — обычный ход с полным
        # входящим. Сравниваем с ней, а не с 0: иначе Уклонение/Отступление (только снижают
        # входящий) никогда не перебили бы «просто постоять/пойти» и голова мертва.
        if chosen is not None:
            baseline = chosen[0]
        else:
            baseline = self._best_move_line(normal, me_cell, enemies,
                                            0.0, dodge=False, avoid=False)[0]
        best_kind, best_val, best_dirs = None, baseline, None
        if "dodge" in items:
            val, dirs = self._best_move_line(normal, me_cell, enemies,
                                             w.dodge_bonus, dodge=True, avoid=False)
            if val > best_val:
                best_kind, best_val, best_dirs = "dodge", val, dirs
        if "disengage" in items:
            val, dirs = self._best_move_line(normal, me_cell, enemies,
                                             w.disengage_bonus, dodge=False, avoid=True)
            if val > best_val:
                best_kind, best_val, best_dirs = "disengage", val, dirs
        if "dash" in items:
            dash = reachable_paths(pf, me_cell, ctx.src_id, ctx.speed_steps * 2)
            extra = {c: p for c, p in dash.items() if c not in normal}
            if extra:
                val, dirs = self._best_move_line(extra, me_cell, enemies,
                                                 w.dash_bonus, dodge=False, avoid=False)
                if val > best_val:
                    best_kind, best_val, best_dirs = "dash", val, dirs
        if best_kind is None:
            return None
        return [move_action(d) for d in (best_dirs or [])] + [use_action(items[best_kind]["id"])]

    def plan(self, ctx: BattleContext):
        """Действия по готовому контексту — для closed-loop сравнения на нашей симуляции."""
        return self._actions(ctx, observe(ctx))

    def label(self, payload: Dict[str, Any]) -> Labeled:
        """payload -> план battlecast-политики; value — на шкале НАШЕЙ симуляции (rollout).

        Обёртка над label_ctx (тот же план с живым контекстом) — единый источник разметки
        для стартовых сцен и для посещённых DAgger состояний.
        """
        return self.label_ctx(BattleContext.from_payload(payload))

    def label_ctx(self, ctx: BattleContext) -> Labeled:
        """Разметить ГОТОВЫЙ контекст (живое состояние из среды) — вход для DAgger-агрегации."""
        actions = self._actions(ctx, observe(ctx))
        # Значение — общей шкалой (rollout), а не внутренней суммой эвристик battlecast.
        value = rollout(ctx, actions, self.value_rounds)
        return Labeled(ctx=ctx, actions=actions, value=value,
                       score=Scorer().score(ctx, actions), depth=1)
