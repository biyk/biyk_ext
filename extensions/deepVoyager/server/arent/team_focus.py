# arent/team_focus.py — `wesnoth_focusfire`: КОМАНДНЫЙ залп (идея Wesnoth AI, без их кода).
#
# Почему не одиночный учитель. Контракт `TeacherPolicy.plan(ctx)` размечает ход ОДНОГО
# актёра, поэтому «focus-fire» внутри него был бы battlecast под другим именем (это прямо
# запрещено планом). Настоящая координация живёт на уровень выше: `team_eval.TeacherController`
# создаётся на БОЙ и вызывается по очереди за каждого живого союзника по инициативе. Значит
# команда может держать ОДИН план на раунд и раздавать союзникам общую цель.
#
# Что здесь честно нового (не переименование):
#  • `team_focus_target(ctx)` — цель выбирается по СИЛАМ КОМАНДЫ: суммарный ожидаемый урон
#    ВСЕХ живых союзников, способных достать врага в этом раунде (свои оружия/скорости из
#    per-token записей), сравнивается с его hp. Если команда добивает — все бьют её; если
#    нет — самую опасную (EV её удара). Одиночный учитель такой информации не имеет.
#  • `WesnothFocusFireTeacher` — stateless-исполнитель: при `preferred_target=None` он
#    ПОБИТОВО battlecast (якорь-тест), с целью — бьёт её, когда она достижима, иначе честный
#    фолбэк на базу (не «идти в недостижимую цель»).
#  • `TeamFocusController` — план раунда + границы: новый раунд (актёр повторился), смерть
#    цели и новая битва (состав/HP) пересчитывают план; между боями состояние не течёт.
from typing import Any, Dict, List, Optional

from planner.context import BattleContext
from planner.geometry import cell_distance
from planner.los import has_los, sight_segments
from planner.payload import actor_gear
from planner.points import tuning

from arent import spec
from arent.battlecast import BattlecastTeacher
from arent.battlecast_heuristics import expected_hit_damage
from arent.teachers import register
from arent.team_eval import TeacherController


def _team_tokens(ctx: BattleContext) -> List[Any]:
    """Живые союзники ТЕКУЩЕГО актёра (та же группировка disposition, что у контекста)."""
    mine = ctx.src.disposition
    out = []
    for t in ctx.tokens:
        if not t.is_alive or t.disposition == 0:
            continue
        same = (t.disposition == -2) if mine == -2 else (t.disposition == mine)
        if same:
            out.append(t)
    return out


def _enemy_ac(ctx: BattleContext, token_id: str) -> float:
    """КД врага из его сырой записи npcs[]; нет данных -> 0 (spec.hit_chance берёт fallback)."""
    entry = next((n for n in (ctx.raw.get("npcs") or []) if n.get("id") == token_id), {}) or {}
    try:
        return float(entry.get("ac") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _enemy_threat(enemy: Any) -> float:
    """EV удара врага (урон × шанс) — «опасность» для приоритета, когда добить нечего."""
    return float(enemy.sim_damage_avg) * float(enemy.sim_hit_chance)


def team_damage_on(ctx: BattleContext, allies: List[Any], enemy: Any) -> float:
    """Суммарный ожидаемый урон команды по врагу за этот раунд (движение + зоны оружия).

    Для каждого союзника берём ЕГО оружие/скорость (`actor_gear`), проверяем, что после
    хода он достаёт врага (`mode_at` по остатку дистанции) и что есть линия видимости из
    текущей клетки. Это консервативная оценка (атака может быть из другой клетки), зато
    детерминированная и на наших же примитивах, а не выдуманная формула.
    """
    fallback = tuning().hit_chance
    ac = _enemy_ac(ctx, enemy.id)
    e_cell = ctx.cell_of(enemy)
    segments = sight_segments(ctx)
    total = 0.0
    for ally in allies:
        a_cell = ctx.cell_of(ally)
        if not has_los(ctx, a_cell, e_cell, segments):
            continue
        weapons, speed = actor_gear(ctx.raw, ally.id, ctx.weapons, ctx.speed_steps)
        reach = max(0.0, cell_distance(a_cell, e_cell) - int(speed))
        best = 0.0
        for weapon in weapons:
            if weapon.mode_at(reach) is None:
                continue
            best = max(best, expected_hit_damage(weapon, ac, fallback))
        total += best
    return total


def team_focus_target(ctx: BattleContext) -> Optional[str]:
    """Цель командного залпа: добиваемая сообща (иначе — самая опасная). Детерминировано.

    Приоритет: (1) враги, которых команда убивает в этом раунде (суммарный EV >= hp) —
    чтобы залп не «размазывался»; (2) среди них — опаснее (EV его удара), затем легче
    (меньше hp), затем id. Если убить не может никого — фокус на самом опасном, чтобы
    следующий раунд добить его.
    """
    enemies = ctx.hostile_targets()
    if not enemies:
        return None
    allies = _team_tokens(ctx)
    killable = [e for e in sorted(enemies, key=lambda t: t.id)
                if team_damage_on(ctx, allies, e) >= float(e.hp_current) > 0]
    pool = killable or list(enemies)
    ranked = sorted(pool, key=lambda e: (-_enemy_threat(e), float(e.hp_current), e.id))
    return ranked[0].id


@register("wesnoth_focusfire")
class WesnothFocusFireTeacher(BattlecastTeacher):
    """Исполнитель командного плана: бьёт назначенную цель, если она достижима.

    `preferred_target=None` -> ровно battlecast (проверено якорь-тестом), поэтому учитель
    годится и для одиночной разметки BC/DAgger. Цель ставит `TeamFocusController` (команда).
    """

    preferred_target: Optional[str] = None

    def choose(self, ctx: BattleContext, obs: Dict[str, Any]):
        preferred = self.preferred_target
        if preferred:
            focused = [e for e in self._enemies(ctx, obs) if e.id == preferred]
            if focused:
                best = self._choose_from(ctx, obs, focused)
                if best is not None and best[5]:        # есть реальный удар по цели
                    return best
        return super().choose(ctx, obs)                  # недостижима -> обычный выбор базы


class TeamFocusController:
    """Тимовый контроллер: один план залпа на раунд, исполнение — учителем по слотам.

    Контракт контроллера team_eval (`_is_controller`/`label`), поэтому подключается везде,
    где имя учителя: BC-демо, PPO-оппонент (`collect_asymmetric`), гейт, closed-loop A/B.
    Внутренняя разметка делегируется `TeacherController` — формат слотов общий с обучением.
    """

    _is_controller = True

    def __init__(self, schema: Optional[int] = None, teacher: Optional[Any] = None):
        self.teacher = teacher if teacher is not None else WesnothFocusFireTeacher(rounds=1)
        self.inner = TeacherController(self.teacher, schema)
        self.schema = self.inner.schema
        self.name = getattr(self.teacher, "name", "wesnoth_focusfire")
        self.last_baseline: Optional[Dict[str, int]] = None
        self.round_seen: List[str] = []
        self.preferred_target: Optional[str] = None
        self._ids: frozenset = frozenset()
        self._hp: Dict[str, float] = {}

    def describe(self) -> str:
        return "wesnoth_focusfire@schema%d" % self.schema

    def reset(self) -> None:
        """Сброс на новую битву (новый контроллер и так создаётся на бой, но не полагаемся)."""
        self.round_seen = []
        self.preferred_target = None
        self._ids = frozenset()
        self._hp = {}

    def _new_battle(self, ctx: BattleContext) -> bool:
        """Новый бой распознаём по составу и «подросшему» HP (payload сбрасывает урон)."""
        ids = frozenset(t.id for t in ctx.tokens)
        if ids != self._ids:
            return True
        return any(t.hp_current > self._hp.get(t.id, t.hp_current) for t in ctx.tokens)

    def _sync_round(self, ctx: BattleContext) -> None:
        if self._new_battle(ctx):
            self.reset()
        if ctx.src_id in self.round_seen:                # актёр повторился -> новый раунд
            self.round_seen = []
            self.preferred_target = None
        self.round_seen.append(ctx.src_id)
        target = ctx.token(self.preferred_target) if self.preferred_target else None
        if target is None or not target.is_alive:
            self.preferred_target = team_focus_target(ctx)
        self._ids = frozenset(t.id for t in ctx.tokens)
        self._hp = {t.id: float(t.hp_current) for t in ctx.tokens}

    def label(self, obs: Dict[str, Any], ctx: BattleContext, slots: Any) -> Dict[str, int]:
        self._sync_round(ctx)
        self.teacher.preferred_target = self.preferred_target
        return self.inner.label(obs, ctx, slots)
