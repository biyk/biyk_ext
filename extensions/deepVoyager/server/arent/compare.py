# arent/compare.py — сравнение учителей на одинаковых состояниях и сценариях (без обучения).
#
# Общая оценка — НАША симуляция (Simulation.advance/foes_act), а не формула каждого
# учителя: обе политики ведут одного и того же src-героя по одним и тем же стартовым
# сценам, и мы мерим исход (выжил/зачистил/раунды/урон), долю состояний с корректной
# меткой и стоимость. ho_* и замороженный holdout исключены (exclude_independent=True).
import random
import time
from statistics import mean
from typing import Any, Dict, List, Tuple

from arent.dataset import sample_one, sources
from arent.teacher import pinned
from arent.teachers import get_teacher
from planner.context import BattleContext
from planner.scoring import Scorer
from planner.sim import Simulation
from planner.turns import rollout


def build_states(scenarios: List[Tuple[str, Dict[str, Any]]], seed: int, per_src: int,
                 rounds_max: int) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """Один и тот же список состояний для всех учителей: (имя, payload, meta)."""
    from arent.states import variants
    rng = random.Random(seed)
    states = []
    for name, payload in scenarios:
        for state_payload, meta in variants(payload, rng, count=per_src, rounds_max=rounds_max):
            states.append((name, state_payload, meta))
    return states


def fight(teacher: Any, payload: Dict[str, Any], rounds: int) -> Dict[str, Any]:
    """Один бой политикой учителя на нашей симуляции; копит исход, урон туда/обратно и ценность.

    value — общая шкала Simulation.advance (Scorer плана + штраф ответа врагов), а не
    внутренняя эвристика учителя: обе политики меряются одними весами (damage/death из points).
    """
    state = Simulation.of(BattleContext.from_payload(payload))
    foes_total, played = len(state.foes), 0
    dealt = taken = total_value = 0.0
    while played < max(1, int(rounds)) and not state.hero_dead and state.foes:
        ctx = state.context_for(state.hero_id)
        actions = teacher.plan(ctx)
        round_value = Scorer().score(ctx, actions)
        before = {u.id: u.hp for u in state.foes}
        hero_before = state.hero.hp
        mid = state.apply_hero(actions)
        dealt += sum(max(0.0, hp - mid.units[u].hp) for u, hp in before.items() if u in mid.units)
        state, penalty = mid.foes_act()
        total_value += round_value + penalty        # ровно advance(actions)[1], но одним проходом
        taken += max(0.0, hero_before - state.hero.hp)
        played += 1
    return {"rounds": played, "survived": not state.hero_dead, "cleared": not state.foes,
            "foes": foes_total, "foes_left": len(state.foes), "rollout": round(total_value, 3),
            "dmg_dealt": round(dealt, 2), "dmg_taken": round(taken, 2)}


def _coverage(teacher_name: str, states: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
              teacher_rounds: int) -> Dict[str, Any]:
    """Доля состояний с корректной меткой + стоимость разметки (sample_one легализует план)."""
    impl = get_teacher(teacher_name, rounds=teacher_rounds, time_limit_sec=None)
    ok, skips, times, values = 0, {}, [], []
    for name, payload, meta in states:
        start = time.monotonic()
        sample, reason = sample_one(name, payload, impl, meta)
        times.append(time.monotonic() - start)
        if sample is None:
            skips[reason] = skips.get(reason, 0) + 1
        else:
            ok += 1
            values.append(sample["value"])
    n = max(1, len(states))
    return {"states": len(states), "labelled": ok, "label_rate": round(ok / n, 3),
            "skip": skips, "ms_per_state": round(1000 * mean(times or [0]), 2),
            "mean_value_clamped": round(mean(values), 3) if values else 0.0}


def _quality(teacher_name: str, states: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
             value_rounds: int) -> Dict[str, Any]:
    """Общая поштучная оценка: rollout НАШЕЙ симуляции по плану учителя на тех же состояниях."""
    impl = get_teacher(teacher_name, rounds=1, time_limit_sec=None)
    values = []
    for _n, p, _m in states:
        labeled = impl.label(p)
        if labeled.actions:
            values.append(rollout(labeled.ctx, labeled.actions, value_rounds))
    return {"scored": len(values),
            "mean_common_rollout": round(mean(values), 3) if values else 0.0}


def _loop_summary(rows: List[Dict[str, Any]], ms_total: float) -> Dict[str, Any]:
    n = max(1, len(rows))
    return {"fights": len(rows), "survival_rate": round(sum(r["survived"] for r in rows) / n, 3),
            "clear_rate": round(sum(r["cleared"] for r in rows) / n, 3),
            "mean_rounds": round(mean([r["rounds"] for r in rows]) if rows else 0.0, 2),
            "mean_dmg_dealt": round(mean([r["dmg_dealt"] for r in rows]) if rows else 0.0, 2),
            "mean_dmg_taken": round(mean([r["dmg_taken"] for r in rows]) if rows else 0.0, 2),
            "ms_per_fight": round(1000 * ms_total / n, 2), "rows": rows}


def run(seed: int = 11, per_src: int = 4, rounds_max: int = 2, teacher_rounds: int = 1,
        rounds: int = 8, teachers: Tuple[str, ...] = ("greedy", "battlecast"),
        arenas: List[str] = None, use_live: bool = False) -> Dict[str, Any]:
    """Свод A/B на одинаковых сценах/состояниях; независимый набор (ho_*) исключён."""
    scenarios = list(sources(arenas, use_live, exclude_independent=True))
    states = build_states(scenarios, seed, per_src, rounds_max)
    report = {"seed": seed, "teachers": list(teachers), "n_scenarios": len(scenarios),
              "n_states": len(states), "scenarios": [n for n, _p in scenarios],
              "holdout_excluded": True, "teacher_rounds": teacher_rounds, "rounds_cap": rounds,
              "sampling": {}, "quality": {}, "closed_loop": {}}
    with pinned(rounds=teacher_rounds, time_limit_sec=None):
        for name in teachers:
            report["sampling"][name] = _coverage(name, states, teacher_rounds)
            report["quality"][name] = _quality(name, states, rounds)
            impl = get_teacher(name, rounds=teacher_rounds, time_limit_sec=None)
            rows, start = [], time.monotonic()
            for sname, payload in scenarios:
                rows.append(dict(fight(impl, payload, rounds), name=sname))
            report["closed_loop"][name] = _loop_summary(rows, time.monotonic() - start)
    return report
