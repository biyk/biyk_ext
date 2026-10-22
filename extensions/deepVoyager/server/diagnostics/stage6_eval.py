# diagnostics/stage6_eval.py — ЭТАП 6 (часть 5): диагностическая КОМАНДНАЯ оценка малой BC-модели.
#
# Три политики ведут ОДНОГО и того же героя по ОДНИМ и тем же стартовым состояниям в ОДНОЙ
# симуляции (Simulation.apply_actor_seq + foes_act): обученная BC-сеть (best-чекпойпт smoke-test),
# учитель greedy и учитель battlecast. Цель — НЕ превзойти учителя, а проверить целостность пути
# «данные → модель → исполнение»: сеть вообще делает допустимые ходы, value-голова жива, планами
# с отходом она пользуется, а не замирает.
#
# Сцены: S1–S6 — фиксированные DIAGNOSTIC-арены (заранее выбранный набор ho3_ под разные тактические
# ситуации); независимый набор — остальные ho3_*. ho3_* НИКОГДА не участвовали в обучении
# (dataset.is_independent), поэтому обе группы честны для сравнения; учимся это явно и пишем,
# что выборка МАЛА для устойчивых выводов (это диагностика, не бенчмарк).
#
# Метрики: исход/зачистка, выживание, урон туда/обратно, исполненные атаки, доля недопустимых
# предложений ДО защитного legalize, частота атак не по ближайшему, использование планов с
# перемещением после атаки (attack_cell!=end_cell).
import json
import os
import sys
from statistics import mean
from typing import Any, Dict, List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))     # server/
sys.path.insert(0, _HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from arent import backend, dataset, legalize, net, paths, spec3, slots_v3
from arent.observe import observe
from arent.teachers import get_teacher
from arent.teacher import pinned
from planner.context import BattleContext
from planner.geometry import cell_distance
from planner.scoring import Scorer
from planner.sim import Simulation

OUT_WS = os.path.join(os.path.dirname(_HERE), "stage6_out")
RUN_NAME = "stage6_bc_smoke"
ROUNDS_CAP = 10
INDEPENDENT_PREFIX = "ho3_"
# S1–S6: фиксированные диагностические сцены (покрывают укрытие/LOS/линию/малые/окружение/танк+адд).
S_DIAGNOSTIC = ["ho3_chokepoint_00", "ho3_cover_02", "ho3_line_01", "ho3_pair_05",
                "ho3_ring_04", "ho3_boss_adds_06"]


def _enemy_cells(ctx: BattleContext) -> List[Tuple[str, Any]]:
    return [(t.id, ctx.cell_of(t)) for t in ctx.hostile_targets()]


def _measure(ctx: BattleContext, slots: slots_v3.SlotsV3, label: Dict[str, int]):
    """По (ctx, slots, итоговый label) — атаковано/уход/не-ближайшая цель (только чтение боя)."""
    plan = slots.plans[label["plan"]] if 0 <= label.get("plan", -1) < slots.n_plans else None
    ti, wi = label.get("target", -1), label.get("weapon", -1)
    attacked = 0 <= ti < len(slots.targets) and 0 <= wi < len(slots.weapons) \
        and slots.targets[ti]["alive"]
    m = {"attacked": int(attacked), "retreat": 0, "non_nearest": 0, "killable_target": 0}
    if plan is not None:
        m["retreat"] = int(plan["attack_cell"] != plan["end_cell"])
    if attacked:
        atk = plan["attack_cell"] if plan is not None else ctx.src_cell
        cells = _enemy_cells(ctx)
        tgt_cell = dict(cells).get(slots.targets[ti]["id"])
        if tgt_cell is not None and cells:
            d_chosen = cell_distance(atk, tgt_cell)
            d_min = min(cell_distance(atk, c) for _i, c in cells)
            m["non_nearest"] = int(d_chosen > d_min + 1e-9)
        weapon = slots.weapons[wi]
        tok = ctx.token(slots.targets[ti]["id"])
        w = ctx.weapon(weapon["id"]) if tok else None
        if tok is not None and w is not None:
            m["killable_target"] = int(tok.hp_current <= w.expected_damage)
    return m


def _decide(policy: Any, state: Simulation):
    """Один ход выбранной политикой -> (actions, slots, ctx, label, illegal_before, reason).

    policy = ("net", model) — независимое.argmax-предложение сети, затем legalize;
    policy = ("teacher", impl) — план учителя (легalen по построению), вставляем в слоты v3.
    """
    kind, obj = policy
    ctx = state.context_for(state.hero_id)
    obs = observe(ctx)
    slots = slots_v3.build(ctx, obs)
    key = net.y_key(spec3.SCHEMA)
    if kind == "net":
        out = obj.predict(encode_obs(ctx, obs, slots))
        raw = {key["cells"]: out[key["cells"]], key["targets"]: out[key["targets"]],
               key["weapons"]: out[key["weapons"]]}
        ri, rti, rwi = raw[key["cells"]], raw[key["targets"]], raw[key["weapons"]]
        illegal = int(0 <= rti < len(slots.targets) and 0 <= rwi < len(slots.weapons)
                      and not slots_v3.attackable_v3(slots, ctx, ri, rti, rwi))
        label, reason = legalize.legalize(raw, spec3.SCHEMA, slots, ctx)
    else:
        actions = obj.plan(ctx)
        slots_v3.ensure_plan(slots, ctx, actions)
        label = slots_v3.label_of(ctx, slots, actions)
        illegal, reason = 0, None
        if label is None:                       # план учителя не собрался в слоты — идём как есть
            return actions, slots, ctx, {"plan": -1, "target": -1, "weapon": -1}, 0, "no_label"
    actions = slots_v3.decode(slots, label)
    return actions, slots, ctx, label, illegal, reason


def encode_obs(ctx, obs, slots):
    from arent import encode_v3
    return encode_v3.observation(ctx, obs, slots)


def _fight(policy: Any, payload: Dict[str, Any], rounds: int = ROUNDS_CAP) -> Dict[str, Any]:
    state = Simulation.of(BattleContext.from_payload(payload))
    foes_total = len(state.foes)
    played = 0
    dealt = taken = total_value = 0.0
    agg = {"rounds": 0, "attacks": 0, "illegal_before": 0, "retreat_attacks": 0,
           "non_nearest": 0, "killable": 0, "corrected": 0}
    while played < max(1, int(rounds)) and not state.hero_dead and state.foes:
        actions, slots, ctx, label, illegal, _reason = _decide(policy, state)
        m = _measure(ctx, slots, label)
        before = {u.id: u.hp for u in state.foes}
        round_value = Scorer().score(ctx, actions)
        mid = state.apply_actor_seq(state.hero_id, actions)
        dealt += sum(max(0.0, hp - mid.units[u].hp) for u, hp in before.items()
                     if u in mid.units)
        state, penalty = mid.foes_act()
        total_value += round_value + penalty
        agg["rounds"] += 1
        agg["attacks"] += m["attacked"]
        agg["illegal_before"] += illegal
        agg["retreat_attacks"] += m["retreat"] * m["attacked"]
        agg["non_nearest"] += m["non_nearest"] * m["attacked"]
        agg["killable"] += m["killable_target"]
        played += 1
    return {"rounds": played, "survived": not state.hero_dead, "cleared": not state.foes,
            "foes": foes_total, "foes_left": len(state.foes),
            "value": round(total_value, 3), "dmg_dealt": round(dealt, 2),
            "dmg_taken": round(taken, 2), **agg}


def _summarise(rows: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    n = max(1, len(rows))
    atk = sum(r["attacks"] for r in rows) or 1
    rnd = sum(r["rounds"] for r in rows) or 1
    return {
        "policy": label, "fights": len(rows),
        "clear_rate": round(sum(r["cleared"] for r in rows) / n, 3),
        "survival_rate": round(sum(r["survived"] for r in rows) / n, 3),
        "mean_rounds": round(mean([r["rounds"] for r in rows]) if rows else 0.0, 2),
        "mean_value": round(mean([r["value"] for r in rows]) if rows else 0.0, 3),
        "mean_dmg_dealt": round(mean([r["dmg_dealt"] for r in rows]) if rows else 0.0, 2),
        "mean_dmg_taken": round(mean([r["dmg_taken"] for r in rows]) if rows else 0.0, 2),
        "attacks_executed_total": sum(r["attacks"] for r in rows),
        "attacks_per_round": round(sum(r["attacks"] for r in rows) / rnd, 3),
        "illegal_before_legalize_frac": round(sum(r["illegal_before"] for r in rows) / rnd, 4),
        "non_nearest_attack_frac": round(sum(r["non_nearest"] for r in rows) / atk, 4),
        "retreat_attack_frac": round(sum(r["retreat_attacks"] for r in rows) / atk, 4),
        "killable_attack_total": sum(r["killable"] for r in rows),
        "rows": rows,
    }


def main() -> int:
    prev = paths.workspace()
    paths.set_workspace(OUT_WS)
    try:
        best_path = os.path.join(paths.run_dir(RUN_NAME), "model_best.json")
        if not os.path.exists(best_path):
            print(f"НЕТ best-чекпойнта {best_path} — сначала part 4 (stage6_bc.py)")
            return 2
        model = backend.load_policy(best_path, kind="pure")
        print(f"оценка модели схемы {getattr(model.cfg, 'schema', '?')} (feat_version "
              f"{spec3.FEATURES_VERSION}) по ho3_* — ни одна сцена не участвовала в обучении")

        # независимый набор (все ho3_) и разбивка на S1–S6 / holdout
        ho3 = dataset.independent_sources(use_live=False, prefixes=(INDEPENDENT_PREFIX,))
        ho3_names = {str(n) for n, _p in ho3}
        missing = [n for n in S_DIAGNOSTIC if n not in ho3_names]
        if missing:
            print(f"НЕТ диагностических сцен {missing} в ho3_"); return 2
        s_payloads = dict((str(n), p) for n, p in ho3)
        holdout = [(n, p) for n, p in ho3 if str(n) not in S_DIAGNOSTIC]

        policies = [("bc_net", ("net", model)),
                    ("greedy", ("teacher", get_teacher("greedy", rounds=1, time_limit_sec=None))),
                    ("battlecast", ("teacher", get_teacher("battlecast", rounds=1,
                                                            time_limit_sec=None)))]
        report = {"model_path": os.path.abspath(best_path),
                  "rounds_cap": ROUNDS_CAP,
                  "s_diagnostic": S_DIAGNOSTIC, "holdout": sorted(str(n) for n, _p in holdout),
                  "note": "малая диагностика целостности пути, НЕ бенчмарк превосходства",
                  "groups": {}}
        with pinned(rounds=1, time_limit_sec=None):
            for tag, scenes in (("S1-S6", [(n, s_payloads[n]) for n in S_DIAGNOSTIC]),
                                ("holdout", holdout)):
                for name, policy in policies:
                    rows = [dict(_fight(policy, payload), name=str(sn)) for sn, payload in scenes]
                    report["groups"].setdefault(tag, {})[name] = _summarise(rows, name)

        # сводка по всем ho3 (S1-S6 + holdout) для каждой политики
        all_scenes = [(n, p) for n, p in ho3]
        with pinned(rounds=1, time_limit_sec=None):
            for name, policy in policies:
                rows = [dict(_fight(policy, payload), name=str(sn)) for sn, payload in all_scenes]
                report["groups"].setdefault("all_ho3", {})[name] = _summarise(rows, name)

        out = os.path.join(OUT_WS, "stage6_eval.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)

        for tag in ("S1-S6", "holdout", "all_ho3"):
            print(f"=== {tag} ({len(report['groups'][tag]['bc_net']['rows'])} боёв на политику) ===")
            hdr = f"  {'policy':<12} clear  surv  atk/rd  illegal  nonNear  retreat  dmgDealt"
            print(hdr)
            for pol in ("bc_net", "greedy", "battlecast"):
                s = report["groups"][tag][pol]
                print(f"  {pol:<12} {s['clear_rate']:.2f}   {s['survival_rate']:.2f}  "
                      f"{s['attacks_per_round']:.2f}    {s['illegal_before_legalize_frac']:.3f}   "
                      f"{s['non_nearest_attack_frac']:.3f}    {s['retreat_attack_frac']:.3f}   "
                      f"{s['mean_dmg_dealt']:.1f}")
        # честная оговорка о размере выборки
        nb = len(report["groups"]["S1-S6"]["bc_net"]["rows"])
        nh = len(report["groups"]["holdout"]["bc_net"]["rows"])
        print(f"  выборка мала: S1–S6={nb} боёв, holdout={nh} — оценки DIAGNOSTIC, не значимые")
        print(f"  сохранено: {out}")
        return 0
    finally:
        paths.set_workspace(prev)


if __name__ == "__main__":
    raise SystemExit(main())
