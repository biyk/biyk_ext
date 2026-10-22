# diagnostics/stage7_eval.py — ЭТАП 7 (часть 3): повторная оценка БЕЗ обучения, два декодера.
#
# Те же веса stage6_bc_smoke/model_best.json (не меняем, не дообучаем), те же сцены S1–S6 и
# все 12 ho3_*, что были на этапе 6, та же симуляция (apply_actor_seq + foes_act). Отличие —
# СПОСОБ декодирования головы->действие и РАЗДЕЛЬНЫЕ метрики семантики (часть 2):
#   • net_indep — СТАРЫЙ путь: независимый argmax трёх голов + legalize (baseline);
#   • net_joint — новый фактический путь: общий joint-декодер (joint.decode = максимум
#     совместной вероятности по A(s)) + защитный legalize, который обязан быть тождеством;
#   • greedy / battlecast — учителя без сети (их legalize не вызывается, план легален).
#
# Метрики по каждой политике (агрегат + по отдельным боям): clear/survival, урон, число и
# доля исполненных атак, доля НЕЗАВИСИМЫХ предсказаний вне A(s) (baseline-диагностика),
# доля фактически выбранных политикой недопустимых действий, число вызовов legalize и
# фактических исправлений, частота не-ближайшей цели, частота hit-and-run (attack!=end).
# Выборка мала: это сравнение ДЕКОДЕРОВ и целостности интеграции, не статистическое
# превосходство. Результаты — в отдельный каталог stage7_out (этап 6 не трогает).
import hashlib
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

from arent import backend, dataset, joint, legalize, net, paths, spec3, slots_v3
from arent.observe import observe
from arent.teachers import get_teacher
from arent.teacher import pinned
from planner.context import BattleContext
from planner.geometry import cell_distance
from planner.scoring import Scorer
from planner.sim import Simulation

OUT_WS = os.path.join(os.path.dirname(_HERE), "stage7_out")
STAGE6_WS = os.path.join(os.path.dirname(_HERE), "stage6_out")
RUN_NAME = "stage6_bc_smoke"
ROUNDS_CAP = 10
INDEPENDENT_PREFIX = "ho3_"
# S1–S6 — те же фиксированные диагностические сцены, что на этапе 6 (замороженный список).
S_DIAGNOSTIC = ["ho3_chokepoint_00", "ho3_cover_02", "ho3_line_01", "ho3_pair_05",
                "ho3_ring_04", "ho3_boss_adds_06"]


def _sha(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _enemy_cells(ctx: BattleContext) -> List[Tuple[str, Any]]:
    return [(t.id, ctx.cell_of(t)) for t in ctx.hostile_targets()]


def _measure(ctx: BattleContext, slots: slots_v3.SlotsV3, label: Dict[str, int]) -> Dict[str, int]:
    """По (ctx, slots, label) — атаковано/уход/не-ближайшая (только чтение боя; как на этапе 6)."""
    plan = slots.plans[label["plan"]] if 0 <= label.get("plan", -1) < slots.n_plans else None
    ti, wi = label.get("target", -1), label.get("weapon", -1)
    attacked = 0 <= ti < len(slots.targets) and 0 <= wi < len(slots.weapons) \
        and slots.targets[ti]["alive"]
    m = {"attacked": int(attacked), "retreat": 0, "non_nearest": 0}
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
    return m


def _decide(policy: Tuple[str, Any], state: Simulation):
    """Один ход политикой -> (actions, ctx, slots, label, stat-шага).

    kind='net_indep' — старый путь (независимый argmax + legalize): считаем, был ли СЫРОЙ
    argmax вне A(s) и правился ли он. kind='net_joint' — фактический путь (joint.decode +
    защитный legalize): baseline-недопустимость считается по независимому argmax
    ЛОГИЧЕСКИ (диагностика), а действие политики — из совместного максимума; починка
    joint-выбора = нарушение контракта. kind='teacher' — план учителя легален по построению.
    """
    kind, obj = policy
    ctx = state.context_for(state.hero_id)
    obs = observe(ctx)
    slots = slots_v3.build(ctx, obs)
    step = {"baseline_outside": 0, "chosen_outside": 0, "legalize_calls": 0,
            "corrections": 0, "violations": 0}
    key = net.y_key(spec3.SCHEMA)
    if kind in ("net_indep", "net_joint"):
        sample = _encode_obs(ctx, obs, slots)
        mask = joint.legal_mask(slots, ctx, spec3.SCHEMA)
        out = obj.predict(sample)
        raw = {key["cells"]: out[key["cells"]], key["targets"]: out[key["targets"]],
               key["weapons"]: out[key["weapons"]]}
        if kind == "net_joint":
            dec = joint.decode(obj, sample, slots, ctx, spec3.SCHEMA)
            raw = joint.independent_baseline(dec["logp"], spec3.SCHEMA)   # тот же baseline
            proposal = dec["label"]
        else:
            proposal = dict(raw)
        step["baseline_outside"] = int(not joint.is_jointly_legal(raw, mask, spec3.SCHEMA))
        step["chosen_outside"] = int(not joint.is_jointly_legal(proposal, mask, spec3.SCHEMA))
        label, reason = legalize.legalize(dict(proposal), spec3.SCHEMA, slots, ctx)
        step["legalize_calls"] = 1
        step["corrections"] = int(bool(reason))
        if kind == "net_joint":
            step["violations"] = int(bool(reason) or dict(label) != dict(proposal))
    else:
        actions = obj.plan(ctx)
        slots_v3.ensure_plan(slots, ctx, actions)
        label = slots_v3.label_of(ctx, slots, actions)
        if label is None:                   # план учителя не собрался в слоты — стоим/не атакуем
            label = {"plan": 0, "target": spec3_none(), "weapon": spec3_none()}
    actions = slots_v3.decode(slots, label)
    return actions, ctx, slots, label, step


def spec3_none() -> int:
    from arent import spec
    return spec.NONE_SLOT


def _encode_obs(ctx, obs, slots):
    from arent import encode_v3
    return encode_v3.observation(ctx, obs, slots)


def _fight(policy: Tuple[str, Any], payload: Dict[str, Any], rounds: int = ROUNDS_CAP) -> Dict[str, Any]:
    state = Simulation.of(BattleContext.from_payload(payload))
    foes_total = len(state.foes)
    played = 0
    dealt = total_value = 0.0
    agg = {"rounds": 0, "attacks": 0, "retreat_attacks": 0, "non_nearest": 0,
           "zero_dmg_attacks": 0, "baseline_outside": 0, "chosen_outside": 0,
           "legalize_calls": 0, "corrections": 0, "violations": 0}
    while played < max(1, int(rounds)) and not state.hero_dead and state.foes:
        actions, ctx, slots, label, step = _decide(policy, state)
        m = _measure(ctx, slots, label)
        before = {u.id: u.hp for u in state.foes}
        round_value = Scorer().score(ctx, actions)
        mid = state.apply_actor_seq(state.hero_id, actions)
        dmg = sum(max(0.0, hp - mid.units[u].hp) for u, hp in before.items() if u in mid.units)
        dealt += dmg
        state, penalty = mid.foes_act()
        total_value += round_value + penalty
        agg["rounds"] += 1
        agg["attacks"] += m["attacked"]
        agg["retreat_attacks"] += m["retreat"] * m["attacked"]
        agg["non_nearest"] += m["non_nearest"] * m["attacked"]
        agg["zero_dmg_attacks"] += int(m["attacked"] and dmg <= 0.0)
        for k in ("baseline_outside", "chosen_outside", "legalize_calls", "corrections",
                  "violations"):
            agg[k] += step[k]
        played += 1
    return {"rounds": played, "survived": not state.hero_dead, "cleared": not state.foes,
            "foes": foes_total, "foes_left": len(state.foes),
            "value": round(total_value, 3), "dmg_dealt": round(dealt, 2), **agg}


def _summarise(rows: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    n = max(1, len(rows))
    atk = sum(r["attacks"] for r in rows) or 1
    rnd = sum(r["rounds"] for r in rows) or 1
    calls = sum(r["legalize_calls"] for r in rows)
    return {
        "policy": label, "fights": len(rows),
        "clear_rate": round(sum(r["cleared"] for r in rows) / n, 3),
        "survival_rate": round(sum(r["survived"] for r in rows) / n, 3),
        "mean_rounds": round(mean([r["rounds"] for r in rows]) if rows else 0.0, 2),
        "mean_value": round(mean([r["value"] for r in rows]) if rows else 0.0, 3),
        "mean_dmg_dealt": round(mean([r["dmg_dealt"] for r in rows]) if rows else 0.0, 2),
        "attacks_executed_total": sum(r["attacks"] for r in rows),
        "attacks_per_round": round(sum(r["attacks"] for r in rows) / rnd, 3),
        # метрика НЕЗАВИСИМОГО baseline-предсказания (старый декодер), не ошибки политики:
        "baseline_illegal_frac": round(sum(r["baseline_outside"] for r in rows) / rnd, 4),
        # доля фактически ВЫБРАННЫХ политикой действий вне A(s) — для joint обязана быть 0:
        "policy_illegal_frac": round(sum(r["chosen_outside"] for r in rows) / rnd, 4),
        "legalize_calls": calls,
        "legalize_corrections": sum(r["corrections"] for r in rows),
        "joint_contract_violations": sum(r["violations"] for r in rows),
        "zero_damage_attacks": sum(r["zero_dmg_attacks"] for r in rows),
        "non_nearest_attack_frac": round(sum(r["non_nearest"] for r in rows) / atk, 4),
        "retreat_attack_frac": round(sum(r["retreat_attacks"] for r in rows) / atk, 4),
        "retreat_attack_total": sum(r["retreat_attacks"] for r in rows),
        "rows": rows,
    }


def main() -> int:
    os.makedirs(OUT_WS, exist_ok=True)
    best_path = os.path.join(STAGE6_WS, "runs", RUN_NAME, "model_best.json")
    if not os.path.exists(best_path):
        print(f"НЕТ best-чекпойнта {best_path}")
        return 2
    sha_before = _sha(best_path)
    model = backend.load_policy(best_path, kind="pure")   # веса НЕ меняем (оценка, не обучение)
    print(f"чекпойнт {best_path}\n  sha256={sha_before[:16]}… (сверяется после прогона)")

    ho3 = dataset.independent_sources(use_live=False, prefixes=(INDEPENDENT_PREFIX,))
    ho3_names = {str(n) for n, _p in ho3}
    missing = [n for n in S_DIAGNOSTIC if n not in ho3_names]
    if missing:
        print(f"НЕТ диагностических сцен {missing} в ho3_")
        return 2
    s_payloads = dict((str(n), p) for n, p in ho3)
    holdout = [(n, p) for n, p in ho3 if str(n) not in S_DIAGNOSTIC]

    policies = [("net_indep", ("net_indep", model)),
                ("net_joint", ("net_joint", model)),
                ("greedy", ("teacher", get_teacher("greedy", rounds=1, time_limit_sec=None))),
                ("battlecast", ("teacher", get_teacher("battlecast", rounds=1,
                                                       time_limit_sec=None)))]
    report = {"model_path": os.path.abspath(best_path), "model_sha256_before": sha_before,
              "rounds_cap": ROUNDS_CAP,
              "s_diagnostic": S_DIAGNOSTIC, "holdout": sorted(str(n) for n, _p in holdout),
              "note": "сравнение двух декодеров на ОДНИХ весах и одних стартовых состояниях; "
                      "выборка мала — это проверка интеграции, не статистическое превосходство",
              "metric_semantics": {
                  "baseline_illegal_frac": "доля шагов, где НЕЗАВИСИМЫЙ argmax голов (старый "
                                           "decode) предложил тройку вне A(s) — диагностика "
                                           "baseline, не ошибка политики",
                  "policy_illegal_frac": "доля шагов, где действие, ВЫБРАННОЕ политикой, вне A(s) "
                                         "у joint-декодера обязано быть 0",
                  "legalize_calls": "число вызовов legalize по сети (защитная проверка)",
                  "legalize_corrections": "число ФАКТИЧЕСКИХ правок действия",
                  "joint_contract_violations": "joint-выбор, изменённый legalize (нарушение "
                                               "контракта, должно быть 0)",
                  "retreat_attack_frac": "доля атак с attack_cell != end_cell (hit-and-run)"},
              "groups": {}}
    with pinned(rounds=1, time_limit_sec=None):
        for tag, scenes in (("S1-S6", [(n, s_payloads[n]) for n in S_DIAGNOSTIC]),
                            ("holdout", holdout),
                            ("all_ho3", [(n, p) for n, p in ho3])):
            for name, policy in policies:
                rows = [dict(_fight(policy, payload), name=str(sn)) for sn, payload in scenes]
                report["groups"].setdefault(tag, {})[name] = _summarise(rows, name)

    sha_after = _sha(best_path)
    report["model_sha256_after"] = sha_after
    report["weights_unchanged"] = sha_before == sha_after

    out = os.path.join(OUT_WS, "stage7_eval.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    for tag in ("S1-S6", "holdout", "all_ho3"):
        g = report["groups"][tag]
        print(f"=== {tag} ({len(g['net_indep']['rows'])} боёв на политику) ===")
        print(f"  {'policy':<12} clear  surv  atk/rd  baseOut  polOut  corr  retreat  dmg")
        for name, _p in policies:
            s = g[name]
            print(f"  {name:<12} {s['clear_rate']:.2f}   {s['survival_rate']:.2f}  "
                  f"{s['attacks_per_round']:.2f}    {s['baseline_illegal_frac']:.3f}   "
                  f"{s['policy_illegal_frac']:.3f}  {s['legalize_corrections']:<5d}  "
                  f"{s['retreat_attack_frac']:.3f}   {s['mean_dmg_dealt']:.1f}")
    print(f"  веса не изменились: {report['weights_unchanged']} "
          f"({sha_before[:12]}… == {sha_after[:12]}…)")
    print(f"  сохранено: {out}")
    ok = (report["groups"]["all_ho3"]["net_joint"]["policy_illegal_frac"] == 0.0
          and report["groups"]["all_ho3"]["net_joint"]["joint_contract_violations"] == 0
          and report["weights_unchanged"])
    print(f"  КОНТРАКТ: joint не выбрал ни одного действия вне A(s) и не был починен: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
