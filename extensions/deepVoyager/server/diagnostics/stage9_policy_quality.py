# diagnostics/stage9_policy_quality.py — ЭТАП 9, часть D: качество политики на НОВОМ holdout.
#
# НОВЫЙ независимый набор: 12 командных сцен из scenarios.generate со СВОИМ seed (hold9_*),
# собранные В ПАМЯТИ и сохранённые только в stage9_out (playground/arenas и ho3_* не трогаются;
# имена проверены на непересечение с аренами обучения). ho3_* для настройки НЕ используем —
# он уже светился в сравнениях этапов 6–7. ЗАПУСКАТЬ ПОСЛЕ частей B/C (_holdout не трогать
# до завершения настройки_).
#
# Сравнивает на ОДНИХ состояниях/сценариях:
#   greedy, battlecast — учителя; bc_joint — BC v3 (stage8 best) через joint.decode (serving);
#   bc_indep — независимый argmax как ДИАГНОСТИЧЕСКИЙ baseline (не политика).
# Два РАЗНЫХ среза (не смешивать!):
#   1) предсказание меток: joint NLL / decode-accuracy против метки greedy на НАЧАЛЬНЫХ
#      состояниях сцен (метку даёт сам учитель, reading-only);
#   2) боевой результат: 10 раундов симуляции — clear/survive/урон/атоки, частота и ДОСТУПНОСТЬ
#      hit-and-run, добивание (missed/correct finisher), не-ближайшая цель, нарушения A(s).
import copy
import json
import os
import sys
import zlib
from statistics import mean

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))     # server/
sys.path.insert(0, _HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from arent import backend, dataset, joint, legalize, net, paths, scenarios, slots_v3, spec3
from arent.observe import observe
from arent.teachers import get_teacher
from arent.teacher import pinned
from planner.context import BattleContext
from planner.geometry import cell_distance
from planner.scoring import Scorer
from planner.sim import Simulation

SERVER = os.path.dirname(_HERE)
STAGE6_WS = os.path.join(SERVER, "stage6_out")
STAGE8_WS = os.path.join(SERVER, "stage8_out")
OUT_WS = os.path.join(SERVER, "stage9_out")
MODEL_BEST = os.path.join(STAGE8_WS, "runs", "stage8_bc_smoke", "model_best.json")
HOLD_SEED = 20260922         # НОВЫЙ seed: не 20261022 (ho3) и не 20261021 (ho2)
HOLD_COUNT = 12
HOLD_PREFIX = "hold9_"
ROUNDS_CAP = 10


def build_holdout():
    """Сцены нового holdout в памяти + проверка непересечения с аренами обучения/ho3."""
    from playground import arena
    known = set(arena.list_arenas())
    scenes = []
    for i, (_gen, raw, params) in enumerate(scenarios.generate(HOLD_COUNT, HOLD_SEED)):
        name = f"{HOLD_PREFIX}{params['archetype']}_{i:02d}"
        if name in known:
            raise RuntimeError(f"имя holdout пересекается с боевой ареной: {name}")
        from arent.holdout import stamp_initiative
        stamped = stamp_initiative(copy.deepcopy(raw), name)
        payload = arena.build_payload(stamped, name)
        ctx = scenarios._bc(payload)
        if not ctx.hostile_targets() or not ctx.src.is_alive:
            continue
        scenes.append((name, payload))
    return scenes


def _label_with_teacher(teacher_impl, name, payload):
    order = Simulation.of(BattleContext.from_payload(payload),
                          env_seed=HOLD_SEED ^ zlib.crc32(name.encode("utf-8"))).initiative_order
    sample, reason = dataset.sample_one_v3(name, payload, teacher_impl, {}, order)
    return sample, reason


def static_labels(scenes, model, teachers):
    """Срез 1: NLL/decode против метки greedy (и battlecast) на начальных состояниях."""
    rows = []
    for name, payload in scenes:
        g_sample, g_reason = _label_with_teacher(teachers["greedy"], name, payload)
        if g_sample is None:
            rows.append({"scene": name, "skipped": g_reason})
            continue
        b_sample, _b_reason = _label_with_teacher(teachers["battlecast"], name, payload)
        lcs, lts, lws, _v = model.head_logp(g_sample)
        mask = g_sample["legal"]
        ip, it, iw = joint.ensure_jointly_legal(g_sample, spec3.SCHEMA)
        nll_greedy = joint.logz(mask, lcs, lts, lws) - (lcs[ip] + lts[it] + lws[iw])
        pick = joint.argmax(mask, lcs, lts, lws, spec3.SCHEMA)
        base = joint.independent_baseline({"cells": lcs, "targets": lts, "weapons": lws},
                                          spec3.SCHEMA)
        row = {"scene": name,
               "nll_greedy_label": round(nll_greedy, 4),
               "joint_eq_greedy": int(pick["plan"] == ip and pick["target"] == it
                                      and pick["weapon"] == iw),
               "indep_eq_greedy": int(base["plan"] == ip and base["target"] == it
                                      and base["weapon"] == iw),
               "indep_outside_As": int(not joint.is_jointly_legal(
                   {"plan": base["plan"], "target": base["target"], "weapon": base["weapon"]},
                   mask, spec3.SCHEMA))}
        if b_sample is not None:
            bp, bt, bw = joint.ensure_jointly_legal(b_sample, spec3.SCHEMA)
            row["nll_battlecast_label"] = round(
                joint.logz(mask, lcs, lts, lws) - (lcs[bp] + lts[bt] + lws[bw]), 4)
            row["greedy_eq_battlecast"] = int((ip, it, iw) == (bp, bt, bw))
            row["joint_eq_battlecast"] = int(pick["plan"] == bp and pick["target"] == bt
                                             and pick["weapon"] == bw)
        rows.append(row)
    return rows


def _finisher_info(ctx, slots, label):
    """Добивание: есть ли достижимая «добиваемая» цель; выбрана ли она (correct/missed)."""
    ti, wi = label.get("target", -1), label.get("weapon", -1)
    if not (0 <= ti < len(slots.targets) and 0 <= wi < len(slots.weapons)):
        return {"attacked": 0, "killable_exists": 0, "finisher_correct": 0,
                "finisher_missed": 0, "retreat": int(
                    slots.plans[label["plan"]]["attack_cell"] !=
                    slots.plans[label["plan"]]["end_cell"]) if 0 <= label.get("plan", -1)
                    < slots.n_plans else 0}
    plan = slots.plans[label["plan"]] if 0 <= label.get("plan", -1) < slots.n_plans \
        else {"attack_cell": ctx.src_cell, "end_cell": ctx.src_cell}
    w = ctx.weapon(slots.weapons[wi]["id"])
    killables = []
    for e_i, e in enumerate(slots.targets):
        tok = ctx.token(e["id"])
        if tok is None or not tok.is_alive or w is None:
            continue
        at = ctx.cell_of(tok)
        # достижимость ТОЙ ЖЕ математикой, что у attackable: режим попадания не None
        if w.mode_at(cell_distance(plan["attack_cell"], at)) is not None \
                and tok.hp_current <= w.expected_damage:
            killables.append(e_i)
    return {"attacked": 1, "killable_exists": int(bool(killables)),
            "finisher_correct": int(ti in killables),
            "finisher_missed": int(bool(killables) and ti not in killables),
            "retreat": int(plan["attack_cell"] != plan["end_cell"])}


def fight(policy, payload):
    """Симуляция того же механизма, что этап 7, плюс боевая тактическая диагностика."""
    kind, obj = policy
    state = Simulation.of(BattleContext.from_payload(payload))
    foes_total = len(state.foes)
    played, dealt = 0, 0.0
    agg = {"rounds": 0, "attacks": 0, "retreat": 0, "hn_available": 0, "hn_taken": 0,
           "killable_exists": 0, "finisher_correct": 0, "finisher_missed": 0,
           "chosen_outside": 0, "legalize_calls": 0, "corrections": 0}
    key = net.y_key(spec3.SCHEMA)
    while played < ROUNDS_CAP and not state.hero_dead and state.foes:
        ctx = state.context_for(state.hero_id)
        obs = observe(ctx)
        slots = slots_v3.build(ctx, obs)
        mask = joint.legal_mask(slots, ctx, spec3.SCHEMA)
        if kind == "teacher":
            actions = obj.plan(ctx)
            slots_v3.ensure_plan(slots, ctx, actions)
            label = slots_v3.label_of(ctx, slots, actions) or \
                {"plan": 0, "target": spec3.NONE_SLOT, "weapon": spec3.NONE_SLOT}
        else:
            sample = dataset_enc_obs(ctx, obs, slots)
            if kind == "bc_joint":
                dec = joint.decode(obj, sample, slots, ctx, spec3.SCHEMA)
                proposal = dec["label"]
            else:                                   # bc_indep: диагностический baseline
                out = obj.predict(sample)
                proposal = {key["cells"]: out[key["cells"]], key["targets"]: out[key["targets"]],
                            key["weapons"]: out[key["weapons"]]}
            agg["legalize_calls"] += 1
            label, reason = legalize.legalize(dict(proposal), spec3.SCHEMA, slots, ctx)
            agg["corrections"] += int(bool(reason))
            agg["chosen_outside"] += int(not joint.is_jointly_legal(dict(label), mask,
                                                                   spec3.SCHEMA))
        # hit-and-run ДОСТУПЕН: легальная тройка с атакой и уходом (attack_cell != end_cell)
        hn_avail = 0
        for p_i, pl in enumerate(slots.plans):
            if pl["attack_cell"] == pl["end_cell"]:
                continue
            for t_i in range(len(slots.targets)):
                row = mask[p_i][t_i] if t_i < len(mask[p_i]) else []
                if any(row[w_i] for w_i in range(len(slots.weapons))):
                    hn_avail = 1
                    break
            if hn_avail:
                break
        fin = _finisher_info(ctx, slots, label)
        agg["hn_available"] += hn_avail
        agg["hn_taken"] += int(hn_avail and fin["retreat"] and fin["attacked"])
        agg["attacks"] += fin["attacked"]
        agg["retreat"] += fin["retreat"] * fin["attacked"]
        agg["killable_exists"] += fin["killable_exists"]
        agg["finisher_correct"] += fin["finisher_correct"]
        agg["finisher_missed"] += fin["finisher_missed"]
        before = {u.id: u.hp for u in state.foes}
        actions = slots_v3.decode(slots, label)
        mid = state.apply_actor_seq(state.hero_id, actions)
        dealt += sum(max(0.0, hp - mid.units[u].hp) for u, hp in before.items()
                     if u in mid.units)
        state, _penalty = mid.foes_act()
        agg["rounds"] += 1
        played += 1
    return {"rounds": played, "survived": int(not state.hero_dead),
            "cleared": int(not state.foes), "foes": foes_total,
            "foes_left": len(state.foes), "dmg": round(dealt, 2), **agg}


def dataset_enc_obs(ctx, obs, slots):
    from arent import encode_v3
    return encode_v3.observation(ctx, obs, slots)


def summarise(rows):
    n = max(1, len(rows))
    atk = sum(r["attacks"] for r in rows) or 1
    rnd = sum(r["rounds"] for r in rows) or 1
    kel = sum(r["killable_exists"] for r in rows) or 1
    return {"fights": len(rows),
            "clear": sum(r["cleared"] for r in rows), "survived": sum(r["survived"]
                                                                      for r in rows),
            "clear_rate": round(sum(r["cleared"] for r in rows) / n, 3),
            "survival_rate": round(sum(r["survived"] for r in rows) / n, 3),
            "mean_dmg": round(mean([r["dmg"] for r in rows]), 2),
            "rounds_total": rnd, "attacks_total": sum(r["attacks"] for r in rows),
            "attacks_per_round": round(sum(r["attacks"] for r in rows) / rnd, 3),
            "hn_rounds_available": sum(r["hn_available"] for r in rows),
            "hn_rounds_taken": sum(r["hn_taken"] for r in rows),
            "hn_take_frac_of_available": round(sum(r["hn_taken"] for r in rows) /
                                               max(1, sum(r["hn_available"] for r in rows)), 3),
            "retreat_attacks": sum(r["retreat"] for r in rows),
            "killable_rounds": sum(r["killable_exists"] for r in rows),
            "finisher_correct": sum(r["finisher_correct"] for r in rows),
            "finisher_missed": sum(r["finisher_missed"] for r in rows),
            "chosen_outside_As": sum(r["chosen_outside"] for r in rows),
            "legalize_corrections": sum(r["corrections"] for r in rows),
            "rows": rows}


def main() -> int:
    os.makedirs(OUT_WS, exist_ok=True)
    model = backend.load_policy(MODEL_BEST, kind="pure")   # веса этапа 8 только для оценки
    prev = paths.workspace()
    paths.set_workspace(STAGE6_WS)
    try:
        train_samples = dataset.load("stage6_v3")
    finally:
        paths.set_workspace(prev)
    train_arenas = {str((s.get("meta") or {}).get("arena")) for s in train_samples}

    scenes = build_holdout()
    leaked = [n for n, _p in scenes if n in train_arenas]
    if leaked:
        raise RuntimeError(f"holdout пересекается с аренами обучения: {leaked}")
    with open(os.path.join(OUT_WS, "holdout9_scenes.json"), "w", encoding="utf-8") as f:
        json.dump({"seed": HOLD_SEED, "count": len(scenes),
                   "names": [n for n, _p in scenes],
                   "note": "часть D: новый независимый набор; в playground НЕ писан",
                   "payloads": {n: p for n, p in scenes}}, f, ensure_ascii=False, indent=1)

    teachers = {"greedy": get_teacher("greedy", rounds=1, time_limit_sec=None),
                "battlecast": get_teacher("battlecast", rounds=1, time_limit_sec=None)}
    policies = [("greedy", ("teacher", teachers["greedy"])),
                ("battlecast", ("teacher", teachers["battlecast"])),
                ("bc_joint", ("bc_joint", model)),
                ("bc_indep_diag", ("bc_indep", model))]
    report = {"holdout": {"seed": HOLD_SEED, "scenes": [n for n, _p in scenes],
                          "prefix": HOLD_PREFIX,
                          "disjoint_from_training_arenas": True,
                          "ho3_used": False},
              "note": "ho3_* не использовался; настройка (B/C) завершена до запуска этого "
                      "набора; предсказание меток и боевой результат — РАЗНЫЕ срезы"}
    with pinned(rounds=1, time_limit_sec=None):
        report["static_vs_labels"] = static_labels(scenes, model, teachers)
        st = [r for r in report["static_vs_labels"] if "skipped" not in r]
        ns = max(1, len(st))
        report["static_summary"] = {
            "states_labeled": ns,
            "mean_nll_greedy_label": round(mean(r["nll_greedy_label"] for r in st), 4),
            "mean_nll_battlecast_label": round(mean([r["nll_battlecast_label"] for r in st
                                                     if "nll_battlecast_label" in r] or [0]), 4),
            "joint_decode_eq_greedy": sum(r["joint_eq_greedy"] for r in st),
            "indep_eq_greedy": sum(r["indep_eq_greedy"] for r in st),
            "indep_outside_As": sum(r["indep_outside_As"] for r in st),
            "greedy_eq_battlecast": sum(r.get("greedy_eq_battlecast", 0) for r in st),
            "joint_eq_battlecast": sum(r.get("joint_eq_battlecast", 0) for r in st),
            "frac": {"joint_eq_greedy": round(sum(r["joint_eq_greedy"] for r in st) / ns, 3),
                     "indep_eq_greedy": round(sum(r["indep_eq_greedy"] for r in st) / ns, 3),
                     "teachers_agree": round(sum(r.get("greedy_eq_battlecast", 0)
                                                 for r in st) / ns, 3)}}
        report["fights"] = {}
        for name, policy in policies:
            rows = [dict(fight(policy, payload), scene=n) for n, payload in scenes]
            report["fights"][name] = summarise(rows)

    out = os.path.join(OUT_WS, "stage9_policy_quality.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"static: {json.dumps(report['static_summary'], ensure_ascii=False)}")
    print(f"{'policy':<14} clear surv  dmg   atk/rd hnAv hnTk killOk killMiss outside corr")
    for name, _p in policies:
        s = report["fights"][name]
        print(f"{name:<14} {s['clear']:>4} {s['survived']:>4} {s['mean_dmg']:>5} "
              f"{s['attacks_per_round']:>6} {s['hn_rounds_available']:>4} "
              f"{s['hn_rounds_taken']:>4} {s['finisher_correct']:>6} "
              f"{s['finisher_missed']:>8} {s['chosen_outside_As']:>7} "
              f"{s['legalize_corrections']:>4}")
    print(f"сохранено: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
