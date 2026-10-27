# arent/tactics_detect.py — чистые детекторы тактик поверх StepCtx (§2.2, §11).
#
# Каждый детектор возвращает (applicable, matched): «была ли возможность» и «сделал ли
# выбранный ход именно это». applicable НЕ зависит от разрешения арены — это fact о состоянии;
# гейт «тактика ожидана на этой арене/этапе» накладывается снаружи (allowed в bonus_for и в
# счётчиках §11). Так детектор можно тестировать на синтетике безSimulation, а follow_rate
# считается по всем применимым состояниям, а не по 64 сэмплам.
#
# Все сигналы — из ground-truth (клетки/hp/LOS/роли), НЕ из наблюдения модели (§11.1).
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, Optional, Tuple

from arent.tactics import (ALL_KEYS, BONUS_KEYS, KIND, PENALTY_KEYS,
                           Penalty, StepCtx, Tag, UnitView)
from planner.geometry import cell_distance

TOL = 0.6                 # допуск «вплотную»: соседняя/диагональная клетка (см. reachTolerance)
STACK_DIST = 1.0 + TOL    # «стоят впритык» — дистанция меньше этого
LOW_HP = 0.30             # порог «низкий HP» для retreat/melee_at_low_hp
SOFT_ROLES = frozenset({"ranged", "mobile_archer"})
FEET_PER_CELL = 5.0           # D&D-сетка: 1 клетка = 5 футов
STAND_OFF_FT = 30.0           # «милишник не доберётся на следующем ходу» = 30 футов
STAND_OFF_CELLS = STAND_OFF_FT / FEET_PER_CELL    # 6.0 клеток


@dataclass(frozen=True)
class Detection:
    """Итог прохода детекторов по одному шагу: три непересекающихся набора ключей."""
    applicable: FrozenSet[str] = frozenset()
    fired: FrozenSet[str] = frozenset()        # бонусные ключи, которые выбор совпал
    violated: FrozenSet[str] = frozenset()     # штрафные ключи, которые выбор совершил


# --------------------------------------------------------------------------- геометрия-хелперы
def _alive(units: Tuple[UnitView, ...]) -> Tuple[UnitView, ...]:
    return tuple(u for u in units if u.alive)


def _nearest_dist(cell, units: Tuple[UnitView, ...]) -> float:
    ds = [cell_distance(cell, u.cell) for u in units]
    return min(ds) if ds else float("inf")


def _reachable(ctx: StepCtx) -> Tuple[UnitView, ...]:
    return tuple(f for f in _alive(ctx.foes)
                 if f.los and cell_distance(ctx.cell_after, f.cell) <= ctx.strike_range + TOL)


def _melee_threats(ctx: StepCtx) -> Tuple[UnitView, ...]:
    """Враги, способные ударить в упор (не дальнобойные): источник reach/contacts-угрозы."""
    return tuple(f for f in _alive(ctx.foes) if not f.ranged)


def _is_soft(u: UnitView) -> bool:
    return u.ranged or u.role in SOFT_ROLES


def _target(ctx: StepCtx) -> Optional[UnitView]:
    if not ctx.target_id:
        return None
    return next((f for f in ctx.foes if f.id == ctx.target_id), None)


# --------------------------------------------------------------------------- детекторы
def _no_idle(c: StepCtx):
    foes = _alive(c.foes)
    if not foes:
        return (False, False)
    # §Переразметка (поиск вредных наград): раньше no_idle платил и за сближение БЕЗ атаки,
    # из-за чего политика получала + за беготню без выстрела (богатый трейс: десятки «не
    # атакует, но +no_idle»). Теперь бонус — только за ход, нанесший атаку: морковка ведёт к
    # добиванию, а не к имитации активности. idle_turn ниже всё ещё штрафует чистый простой.
    # §Подпустил = смерть (переделотка наград): морковка «не простаивал» платится ТОЛЬКО вне
    # melee-охвата. Дальнобойнику, простреливающемуся вплотную к ближнему врагу, активность не
    # награждается — иначе «grab-and-shoot» (подошёл, отодвинулся на клетку, выстрелил) перевешивает
    # штраф за то, что подпустил к себе. Для ближников гейт не действует: удар в упор для них нормален.
    return (True, bool(c.attacked) and not (c.actor.ranged and c.in_reach_after))


def _idle_turn(c: StepCtx):
    foes = _alive(c.foes)
    if not foes:
        return (False, False)
    d_before = _nearest_dist(c.actor.cell, foes)
    d_after = _nearest_dist(c.cell_after, foes)
    approached = c.moved and d_after < d_before - 1e-9
    # §Не карать побег: честный отход (увеличил дистанцию без выстрела) — ПРАВИЛЬНОЕ поведение
    # кайтера, раньше ловило −idle_turn и политика предпочитала «стой и стреляй» вместо бегства.
    # Штраф остаётся только на настоящем простою: ни атаки, ни сближения, ни отхода.
    fled = c.moved and d_after > d_before + 1e-9
    return (True, not c.attacked and not approached and not fled)


def _focus_wounded(c: StepCtx):
    reach = _reachable(c)
    tgt = _target(c)
    if not c.attacked or tgt is None or not reach:
        return (bool(reach and c.attacked), False)
    min_frac = min(f.hp_frac for f in reach)
    return (True, tgt.hp_frac <= min_frac + 1e-9 and tgt.hp_frac < 1.0)


def _kill_shot(c: StepCtx):
    tgt = _target(c)
    if not c.attacked or tgt is None or c.dmg_expect <= 0:
        return (bool(c.attacked and c.dmg_expect > 0), False)
    return (True, c.dmg_expect >= c.target_hp_before > 0)


def _priority_soft(c: StepCtx):
    # «Выбор приоритетной (мягкой) цели» имеет смысл только когда врагов НЕСКОЛЬКО: при
    # единственном враге атаковать его мягкую версию — не решение, а единственная опция,
    # награда была бы пустой. Поэтому гейт по числу живых врагов >= 2.
    if len(_alive(c.foes)) < 2:
        return (False, False)
    reach = _reachable(c)
    tgt = _target(c)
    softs = tuple(f for f in reach if _is_soft(f))
    if not c.attacked or tgt is None or not softs:
        return (bool(c.attacked and softs), False)
    return (True, _is_soft(tgt))


def _hit_boss_with_adds(c: StepCtx):
    reach = _reachable(c)
    tgt = _target(c)
    bosses = tuple(f for f in reach if f.role == "tank")
    adds = tuple(f for f in reach if f.role != "tank")
    if not c.attacked or tgt is None or not bosses or not adds:
        return (False, False)
    return (True, tgt.role == "tank")


def _kite_max_range(c: StepCtx):
    measurers = tuple(f for f in _alive(c.foes) if not f.ranged)
    if not c.actor.ranged or not measurers:
        return (False, False)
    before = _nearest_dist(c.actor.cell, measurers)
    after = _nearest_dist(c.cell_after, measurers)
    # §Дисциплина дистанции: засчитываем кайт за ЛЮБОЕ увеличение дистанции + выстрел.
    # Прежний порог (>= speed/2) был недостижим на тесной аренде: 334 applicable, 0 fired.
    return (True, c.attacked and after > before + 1e-9 and not c.in_reach_after)


def _approach_as_archer(c: StepCtx):
    measurers = tuple(f for f in _alive(c.foes) if not f.ranged)
    if not c.actor.ranged or not measurers:
        return (False, False)
    return (True, _nearest_dist(c.cell_after, measurers) < _nearest_dist(c.actor.cell, measurers) - 1e-9)


def _cover_shoot(c: StepCtx):
    if not (c.actor.ranged and c.attacked):
        return (False, False)
    return (True, c.cover_after)


def _stand_off_shoot(c: StepCtx):
    # §Дисциплина дистанции (правило 30 футов): дальнобойный стреляет с такой дистанции, что
    # ближайший ближник НЕ доберётся до него на следующем ходу (>=30 футов = 6 клеток). Прежний
    # критерий «просто вне melee-зоны» (~1-2 клетки) выдавал морковку за стояние вплотную к
    # врагу — это неверно: милишник доставал актёра в ответ. Укрытий на арене нет -> cover_shoot
    # мёртв, и stand_off остаётся основной морковкой Этапа 3, но теперь строго по дистанции.
    if not (c.actor.ranged and c.attacked):
        return (False, False)
    threats = _melee_threats(c)
    if not threats:                               # ближников нет: былое «вне melee-зоны»
        return (True, not c.in_reach_after)
    return (True, _nearest_dist(c.cell_after, threats) >= STAND_OFF_CELLS)


def _shoot_from_open(c: StepCtx):
    if not (c.actor.ranged and c.attacked):
        return (False, False)
    return (True, not c.cover_after)


def _avoid_reach(c: StepCtx):
    # §Дисциплина дистанции (30 футов, только дальнобойник vs милишник): милишник ДЕРЖАЛ
    # дальнобойного в <30 футов до хода, и тот отошёл так, что стал >30 футов после хода —
    # вышел из зоны догона и удара. Величина награды масштабируется запасом сверх 30 футов
    # (см. avoid_reach_steps): каждые 5 футов запаса = один шаг веса.
    threats = _melee_threats(c)
    if not c.actor.ranged or not c.moved or not threats:
        return (False, False)
    before = _nearest_dist(c.actor.cell, threats)
    if before >= STAND_OFF_CELLS:                 # и так был вне 30 футов -> «избегать» не от чего
        return (False, False)
    after = _nearest_dist(c.cell_after, threats)
    return (True, after > STAND_OFF_CELLS)


def avoid_reach_steps(c: StepCtx) -> int:
    """Число 5-футовых шагов запаса сверх 30 футов: множитель веса avoid_reach.

    floor((дистанция_после − 30 футов) / 5 футов) в клетках (1 клетка = 5 футов). 0, если
    avoid_reach не сработал или вышел ровно за 30 (<35 футов запаса). Только источник числа --
    та же геометрия, что и у детектора, поэтому детектор и масштаб не разъедутся."""
    ok, matched = _avoid_reach(c)
    if not (ok and matched):
        return 0
    after = _nearest_dist(c.cell_after, _melee_threats(c))
    return max(0, int(after - STAND_OFF_CELLS))


def _enter_reach(c: StepCtx):
    threats = _melee_threats(c)
    if not threats:
        return (False, False)
    return (True, c.in_reach_after and c.took_damage)


def _reach_penalty(c: StepCtx):
    threats = _melee_threats(c)
    if not c.moved or not threats:
        return (False, False)
    return (True, c.in_reach_after)


def _ranged_grabbed(c: StepCtx):
    # §Штраф «взяли в руки»: дальнобойник закончил СВОЙ ход в melee-охвате хоть одного ближника.
    # Ловит пассивный случай, который пропускают соседи: reach_penalty требует c.moved (сам зашёл),
    # enter_reach требует took_damage (уже отбили). Здесь наказывается само состояние «меня достанут
    # в ближнем бою» — мотив дальнобойнику держать дистанцию/отходить, а не подставлять себя.
    # Ролевой гейт (actor.ranged) не трогает танков/милишников: для них ближний бой нормален.
    threats = _melee_threats(c)
    if not c.actor.ranged or not threats:
        return (False, False)
    return (True, c.in_reach_after)


def _break_ring(c: StepCtx):
    if c.contacts_before < 2:
        return (False, False)
    return (True, c.contacts_after <= 1)


def _widen_contacts(c: StepCtx):
    if c.contacts_before > 1:
        return (False, False)
    return (True, c.contacts_after >= 3 and c.contacts_after > c.contacts_before)


def _hold_choke(c: StepCtx):
    if not c.at_choke_before:
        return (False, False)
    return (True, c.at_choke_after and c.attacked and c.contacts_after <= 1)


def _leave_choke(c: StepCtx):
    if not c.at_choke_before:
        return (False, False)
    return (True, c.at_choke_before and not c.at_choke_after)


def _anti_pincer(c: StepCtx):
    foes = _alive(c.foes)
    if c.contacts_before < 2 or not c.attacked or not foes:
        return (c.contacts_before >= 2, False)
    nearest = min(foes, key=lambda f: cell_distance(c.cell_after, f.cell))
    return (True, c.target_id == nearest.id)


def _no_stack(c: StepCtx):
    allies = _alive(c.allies)
    if not allies or not c.moved:
        return (bool(allies), False)
    return (True, all(cell_distance(c.cell_after, a.cell) > STACK_DIST for a in allies))


def _stack_close(c: StepCtx):
    allies = _alive(c.allies)
    if not allies:
        return (False, False)
    return (True, any(cell_distance(c.cell_after, a.cell) <= STACK_DIST for a in allies))


def _retreat_low_hp(c: StepCtx):
    foes = _alive(c.foes)
    if c.actor.hp_frac >= LOW_HP or not foes:
        return (False, False)
    fled = _nearest_dist(c.cell_after, foes) > _nearest_dist(c.actor.cell, foes) + 1e-9
    # §Дисциплина дистанции: убрали contacts_after==0 — растянуть дистанцию на низком HP
    # уже отход, даже если враг успевает достать. Прежний порог: 277 applicable, 0 fired.
    return (True, c.moved and fled)


def _melee_at_low_hp(c: StepCtx):
    if c.actor.hp_frac >= LOW_HP:
        return (False, False)
    return (True, c.contacts_after >= 1)


def _focus_fire(c: StepCtx):
    if not (c.attacked and _alive(c.allies)):
        return (False, False)
    return (True, c.prior_allies_on_target >= 1)


def _spread_fire(c: StepCtx):
    foes = _alive(c.foes)
    if not (c.attacked and _alive(c.allies) and len(foes) >= 2):
        return (False, False)
    return (True, bool(c.prior_ally_targets) and c.target_id not in c.prior_ally_targets)


#: ключ -> детектор. Отложенные (§10.4) и не реализованные здесь теги отсутствуют: они
#: принципиально неприменимы в движке, поэтому в detect() молчат (applicable==0 -> N/A).
DETECTORS: Dict[str, Callable[[StepCtx], Tuple[bool, bool]]] = {
    Tag.no_idle.value: _no_idle, Penalty.idle_turn.value: _idle_turn,
    Tag.focus_wounded.value: _focus_wounded, Tag.kill_shot.value: _kill_shot,
    Tag.priority_soft.value: _priority_soft, Penalty.hit_boss_with_adds.value: _hit_boss_with_adds,
    Tag.kite_max_range.value: _kite_max_range,
    Penalty.approach_milishnik_as_archer.value: _approach_as_archer,
    Tag.cover_shoot.value: _cover_shoot, Penalty.shoot_from_open.value: _shoot_from_open,
    Tag.stand_off_shoot.value: _stand_off_shoot,
    Tag.avoid_reach.value: _avoid_reach, Penalty.enter_reach.value: _enter_reach,
    Penalty.reach_penalty.value: _reach_penalty,
    Penalty.ranged_grabbed.value: _ranged_grabbed,
    Tag.break_ring.value: _break_ring, Penalty.widen_contacts.value: _widen_contacts,
    Tag.hold_choke.value: _hold_choke, Penalty.leave_choke.value: _leave_choke,
    Tag.anti_pincer.value: _anti_pincer,
    Tag.no_stack.value: _no_stack, Penalty.stack_close.value: _stack_close,
    Tag.retreat_low_hp.value: _retreat_low_hp, Penalty.melee_at_low_hp.value: _melee_at_low_hp,
    Tag.focus_fire.value: _focus_fire, Penalty.spread_fire.value: _spread_fire,
}


def detect(ctx: StepCtx) -> Detection:
    """Пройти все доступные детекторы: собрать applicable/fired/violated."""
    applicable, fired, violated = set(), set(), set()
    for key, fn in DETECTORS.items():
        ok, matched = fn(ctx)
        if ok:
            applicable.add(key)
            if matched:
                (fired if KIND[key] == "bonus" else violated).add(key)
    return Detection(frozenset(applicable), frozenset(fired), frozenset(violated))


def bonus_for(detection: Detection, allowed: Optional[set], weights: Dict[str, float],
              penalties: Dict[str, float], scale: Optional[Dict[str, float]] = None) -> float:
    """Тактический shaping-член шага: Σ (вес × множитель) сработавших бонусов + штрафов, по allowed.

    allowed=None — разрешены все ключи реестра; иначе (set[str]) — arena/stage-гейт §1.4. Неизвестный
    ключ в весах — KeyError, а не молчаливый ноль (§2.3): опечатка в weights не должна «исчезать».
    scale — необязательные множители «за дистанцию» (напр. avoid_reach: вес × каждые 5 футов
    запаса). Ключа нет -> множитель 1.0 (прежний плоский тег). Множитель действует лишь на бонусы.
    """
    for key in weights:
        if key not in BONUS_KEYS:
            raise KeyError(f"tactics.weights: ключ {key!r} вне реестра Tag")
    for key in penalties:
        if key not in PENALTY_KEYS:
            raise KeyError(f"tactics.penalties: ключ {key!r} вне реестра Penalty")
    allow = set(ALL_KEYS) if allowed is None else set(allowed)
    mult = scale or {}
    total = 0.0
    for key in detection.fired & allow:
        total += float(weights.get(key, 0.0)) * float(mult.get(key, 1.0))
    for key in detection.violated & allow:
        total += float(penalties.get(key, 0.0))
    return round(total, 6)


def distance_field_value(c: StepCtx, df) -> float:
    """Непрерывная дистанционная награда дальнобойного (переразметка).

    r = dist(клетка_после .. ближайшая melee-угроза) / R_conf, где R_conf = reach оружия актёра
    (дистанция уверенной атаки). Трапеция: r<near_cut -> штраф; near_cut..peak -> рост к +amp;
    peak..far_cut -> спад к 0; r>far_cut -> 0. Ноль, если актёр не дальнобойный, нет melee-угроз
    или поле выключено (тогда не искажает симметричные перестрелки).
    """
    if not getattr(df, "enabled", False) or not c.actor.ranged:
        return 0.0
    threats = _melee_threats(c)
    if not threats:
        return 0.0
    conf = max(1e-9, float(c.actor.reach))
    r = _nearest_dist(c.cell_after, threats) / conf
    amp = float(df.amp)
    if r < df.near_cut:
        return round(-amp * (df.near_cut - r) / df.near_cut, 6)
    # §Закрыть вредную награду (переразметка): положительная морковка поля платится ТОЛЬКО за
    # ход, нанесший атаку. Иначе дальнобойный фармит +field простой беготнёй от melee-угрозы без
    # единого выстрела — награда растёт от вредного (не ведущего к победе) поведения. Отрицательная
    # ветка (вплотную к melee) выше уже вернула штраф и остаётся в силе и без атаки: он не раздувает
    # награду, а наказывает опасное стояние.
    if not c.attacked:
        return 0.0
    if r <= df.peak:
        return round(amp * (r - df.near_cut) / max(1e-9, df.peak - df.near_cut), 6)
    if r <= df.far_cut:
        return round(amp * (df.far_cut - r) / max(1e-9, df.far_cut - df.peak), 6)
    return 0.0
