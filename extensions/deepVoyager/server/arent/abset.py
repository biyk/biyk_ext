# arent/abset.py — A/B учителей на ЗАФИКСИРОВАННОМ независимом наборе сгенерированных боёв.
#
# Отличие от compare.run: сцены берутся не из 15 рукописных арен + variants (там состав
# зафиксирован файлом, а seed лишь возмущает позиции/hp), а из scenarios.py — структурного
# генератора: архетип × число и классы врагов × оружие героя × поле × стены. Это даёт
# настоящую независимость конфигураций, а не перетасовку одной арены.
#
# Честные рамки: ho_* (замороженный holdout) в набор не входят и не используются нигде;
# правила симуляции и бюджет (rounds-потолок, teacher_rounds, без дедлайна) одинаковы для
# обеих политик; код учителей здесь НЕ меняется — только измеряется. Общая ценность боя —
# накопленная шкала Simulation.advance (compare.fight), не внутренняя эвристика учителя.
import hashlib
import json
import os
import time
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

from playground import arena

from arent import paired, scenarios
from arent.compare import fight
from arent.dataset import sample_one
from arent.states import rebuild
from arent.teacher import pinned
from arent.teachers import get_teacher
from planner.context import BattleContext
from planner.initiative import team_actors
from planner.sim import Simulation

METRICS = ("cleared", "survived", "rounds", "rollout", "dmg_net", "dmg_dealt", "dmg_taken")


def build_set(count: int, seed: int) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """count валидных независимых сцен (name, payload, params); ho_* не производятся."""
    out = []
    for name, raw, params in scenarios.generate(count, seed):
        payload = arena.build_payload(raw, name)
        ctx = BattleContext.from_payload(payload)
        if not ctx.hostile_targets() or not ctx.src.is_alive:
            continue
        assert not name.startswith(("ho_", "ho2_")), f"holdout просочился в набор: {name}"
        out.append((name, payload, params))
    return out


def fingerprint(scenes: List[Tuple[str, Dict[str, Any], Dict[str, Any]]]) -> str:
    """Хеш зафиксированного набора (имена+params), чтобы набор нельзя было подменить постфактум."""
    slurry = sorted([[name, params] for name, _p, params in scenes], key=lambda r: r[0])
    blob = json.dumps(slurry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _rows(teacher_name: str, scenes: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
          rounds: int, teacher_rounds: int, time_limit_sec: Optional[float] = None
          ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """По closed-loop бою на сцену + покрытие разметки по каждому нашему актёру (микро-шагу).

    fight мерит одиночного src-героя (политика eval не меняется), а покрытие размечает каждый
    живой боец нашей команды — ровно те микро-шаги, из которых состоит BC-выборка v2.
    """
    impl = get_teacher(teacher_name, rounds=teacher_rounds, time_limit_sec=time_limit_sec)
    rows, ok, steps, skips, label_ms = [], 0, 0, {}, []
    for name, payload, _params in scenes:
        start = time.monotonic()
        row = fight(impl, payload, rounds)
        row["name"] = name
        row["ms"] = round(1000 * (time.monotonic() - start), 2)
        rows.append(row)
        ctx = BattleContext.from_payload(payload)
        sim = Simulation.of(ctx)
        order = sim.initiative_order
        for actor in team_actors(sim.units, ctx.src_id, order):
            ls = time.monotonic()
            sample, why = sample_one(name, rebuild(payload, actor), impl,
                                     {"src": actor, "rounds": 0, "variant": 0}, order)
            label_ms.append(time.monotonic() - ls)
            steps += 1
            if sample is None:
                skips[why] = skips.get(why, 0) + 1
            else:
                ok += 1
    cov = {"states": len(scenes), "micro_steps": steps, "labelled": ok,
           "label_rate": round(ok / max(1, steps), 3),
           "skip": skips, "ms_per_label": round(1000 * mean(label_ms or [0]), 2)}
    return rows, cov


def trace_fight(teacher_name: str, payload: Dict[str, Any], rounds: int,
               teacher_rounds: int = 1) -> List[Dict[str, Any]]:
    """Поракундная трассировка боя политикой — для разбора конкретных проигрышных решений."""
    from planner.sim import Simulation
    impl = get_teacher(teacher_name, rounds=teacher_rounds, time_limit_sec=None)
    state = Simulation.of(BattleContext.from_payload(payload))
    steps = []
    while len(steps) < max(1, rounds) and not state.hero_dead and state.foes:
        ctx = state.context_for(state.hero_id)
        actions = impl.plan(ctx)
        before = {u.id: u.hp for u in state.foes}
        hero_before = state.hero.hp
        mid = state.apply_hero(actions)
        dealt = sum(max(0.0, hp - mid.units[u].hp) for u, hp in before.items() if u in mid.units)
        state, _pen = mid.foes_act()
        steps.append({"round": len(steps) + 1, "hero_cell": list(state.hero.cell),
                      "actions": [a.to_dict() for a in actions],
                      "dmg_dealt": round(dealt, 2),
                      "hero_hp_after": round(state.hero.hp, 1),
                      "dmg_taken": round(max(0.0, hero_before - state.hero.hp), 2),
                      "foes_left": len(state.foes)})
    return steps


def run(count: int = 80, seed: int = 20261020, rounds: int = 8, teacher_rounds: int = 1,
        teachers: Tuple[str, ...] = ("greedy", "battlecast"), ci_seed: int = 1234,
        depth_map: Optional[Dict[str, int]] = None,
        limit_map: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Прогон политик на одном зафиксированном наборе; парные разности + bootstrap CI.

    depth_map/limit_map — необязательная глубина (rounds) и дедлайн планировщика на учителя:
    по умолчанию все идут на teacher_rounds (сопоставимый одноходовый бюджет). Это даёт
    воспроизводимо сравнить, например, greedy в его штатном lookahead (depth=2/3) против
    однопроходного battlecast — не меняя код политик, только бюджет прогона.
    """
    scenes = build_set(count, seed)
    all_rows, coverage, depths = {}, {}, {}
    for name in teachers:
        depth = (depth_map or {}).get(name, teacher_rounds)
        limit = (limit_map or {}).get(name)
        depths[name] = {"rounds": depth, "time_limit_sec": limit}
        with pinned(rounds=depth, time_limit_sec=limit):
            all_rows[name], coverage[name] = _rows(name, scenes, rounds, depth, limit)
    g, b = teachers[0], teachers[1] if len(teachers) > 1 else teachers[0]
    summary = paired.summarize_paired(all_rows[g], all_rows[b], METRICS, seed=ci_seed)
    report = {"n_scenes": len(scenes), "set_seed": seed, "set_fingerprint": fingerprint(scenes),
              "rounds_cap": rounds, "teacher_rounds": teacher_rounds, "holdout_excluded": True,
              "a_minus_b": f"{g}-{b}", "teachers": list(teachers), "depths": depths,
              "fixed_set": [{"name": n, "params": p} for n, _pl, p in scenes],
              "per_teacher": {name: _agg(all_rows[name], coverage[name]) for name in teachers},
              "paired": summary, "per_scenario": {name: all_rows[name] for name in teachers}}
    return report


def _agg(rows: List[Dict[str, Any]], coverage: Dict[str, Any]) -> Dict[str, Any]:
    n = max(1, len(rows))
    return {"fights": len(rows), "survival_rate": round(sum(r["survived"] for r in rows) / n, 3),
            "clear_rate": round(sum(r["cleared"] for r in rows) / n, 3),
            "mean_rounds": round(mean([r["rounds"] for r in rows]) if rows else 0.0, 2),
            "mean_rollout": round(mean([r["rollout"] for r in rows]) if rows else 0.0, 3),
            "mean_dmg_dealt": round(mean([r["dmg_dealt"] for r in rows]) if rows else 0.0, 2),
            "mean_dmg_taken": round(mean([r["dmg_taken"] for r in rows]) if rows else 0.0, 2),
            "ms_per_fight": round(mean([r["ms"] for r in rows]) if rows else 0.0, 2),
            "coverage": coverage}


def write(report: Dict[str, Any], out_dir: str) -> Dict[str, str]:
    """Пишет набор (fixed_set.json) и результат (abset.json) раздельно; возвращает пути."""
    os.makedirs(out_dir, exist_ok=True)
    set_path = os.path.join(out_dir, "fixed_set.json")
    res_path = os.path.join(out_dir, "abset.json")
    with open(set_path, "w", encoding="utf-8") as f:
        json.dump({"set_fingerprint": report["set_fingerprint"], "set_seed": report["set_seed"],
                   "n_scenes": report["n_scenes"],
                   "scenes": report.get("fixed_set", [])}, f, ensure_ascii=False, indent=1)
    with open(res_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, sort_keys=True)
    return {"set": set_path, "result": res_path}
