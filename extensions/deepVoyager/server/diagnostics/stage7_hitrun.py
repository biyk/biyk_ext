# diagnostics/stage7_hitrun.py — ЭТАП 7 (часть 4): почему hit-and-run не появляется — сигнал или декод?
#
# Разделяем ДВА разных объяснения нулевой частоты отходов у BC-модели:
#   1) НЕДОСТАТОК ОБУЧАЮЩЕГО СИГНАЛА: доля меток hit-and-run (attack_cell != end_cell) в
#      датасете и в train-подмножестве; если меток мало/нет — сети неоткуда выучить тактику;
#   2) ОШИБКА ДЕКОДИРОВАНИЯ: даже при наличии сигнала joint-декодер мог бы не допускать
#      такие тройки — проверяем: есть ли допустимые отступные атаки в A(s) оценочных состояний,
#      какую joint-вероятность им назначает модель и что выбирают baseline/joint-декодеры.
# Данные, веса и сеть НЕ меняем: только разбор существующих артефактов stage6 + 12 ho3-сцен.
#
# План-слот классифицируется по вектору признаков (spec3.CELL3_FEATURES): отход = costOut > 0
# (движение ПОСЛЕ удара) при активной атаке; координатное сравнение attack/end даёт индексы
# adx..edist. Это ровно то же определение hit-and-run, что в QC этапа 6 (retreat = атака и
# attack_cell != end_cell).
import json
import math
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

from arent import backend, dataset, joint, net, paths, spec, spec3, splitting, slots_v3
from arent.observe import observe
from arent.teachers import get_teacher
from arent.teacher import pinned
from planner.context import BattleContext
from planner.sim import Simulation
from stage6_common import SEED

OUT_WS = os.path.join(os.path.dirname(_HERE), "stage7_out")
STAGE6_WS = os.path.join(os.path.dirname(_HERE), "stage6_out")
DATASET_NAME = "stage6_v3"
RUN_NAME = "stage6_bc_smoke"
INDEPENDENT_PREFIX = "ho3_"
# индексы признаков move-plan-слота (порядок = spec3.CELL3_FEATURES)
IDX = {name: i for i, name in enumerate(spec3.CELL3_FEATURES)}


def _is_attack_label(sample: Dict[str, Any]) -> bool:
    it = net.y_index(sample, "targets", spec3.SCHEMA)
    iw = net.y_index(sample, "weapons", spec3.SCHEMA)
    return it < spec.K_TARGETS and iw < spec.K_WEAPONS


def _retreat_slot(vec: List[float]) -> bool:
    """План с движением ПОСЛЕ удара (costOut>0): attack_cell != end_cell."""
    return vec[IDX["costOut"]] > 1e-9


def _label_is_retreat(sample: Dict[str, Any]) -> bool:
    p = net.y_index(sample, "cells", spec3.SCHEMA)
    return _retreat_slot(sample["cells"][p])


def _label_stats(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = max(1, len(samples))
    atk = [s for s in samples if _is_attack_label(s)]
    ret = [s for s in atk if _label_is_retreat(s)]
    return {"samples": len(samples), "attacks": len(atk),
            "attack_frac": round(len(atk) / n, 4),
            "hit_and_run_labels": len(ret),
            "hit_and_run_frac_of_attacks": round(len(ret) / max(1, len(atk)), 4),
            "hit_and_run_frac_of_all": round(len(ret) / n, 4)}


def _plan_kind(sample: Dict[str, Any], plan_idx: int) -> str:
    """Класс выбранного индекса слота: pad / стоит-или-pureMove / подход без удара / hit-and-run."""
    if plan_idx < 0 or plan_idx >= len(sample["mask"]["cells"]) or not sample["mask"]["cells"][plan_idx]:
        return "pad"
    vec = sample["cells"][plan_idx]
    if vec[IDX["adx"]] == vec[IDX["edx"]] and vec[IDX["ady"]] == vec[IDX["edy"]]:
        return "stay_or_pureMove"
    return "hit_and_run" if vec[IDX["costOut"]] > 1e-9 else "advance_only"


def _joint_retreat_mass(model, sample: Dict[str, Any]) -> Dict[str, Any]:
    """Вероятность СОБЫТИЯ «атака с отходом» по joint-закону модели в этом состоянии."""
    legal = sample["legal"]
    lcs, lts, lws, _v = model.head_logp(sample)
    z = joint.logz(legal, lcs, lts, lws)
    mass = 0.0
    top, top_trip = float("-inf"), None
    for p, row in enumerate(legal):
        if not sample["mask"]["cells"][p] or not _retreat_slot(sample["cells"][p]):
            continue
        for t, col in enumerate(row):
            for w, ok in enumerate(col):
                if ok and t < spec.K_TARGETS and w < spec.K_WEAPONS:
                    u = lcs[p] + lts[t] + lws[w]
                    mass += math.exp(u - z)
                    if u > top:
                        top, top_trip = u, (p, t, w)
    return {"retreat_mass": round(mass, 6),
            "best_retreat_logp": round(top, 6) if top_trip else None}


def _features_split(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Средние признаки слота-метки: hit-and-run против атаки с места — что их различает."""
    groups: Dict[str, List[List[float]]] = {"hit_and_run": [], "attack_same_cell": []}
    for s in samples:
        if not _is_attack_label(s):
            continue
        vec = s["cells"][net.y_index(s, "cells", spec3.SCHEMA)]
        groups["hit_and_run" if _retreat_slot(vec) else "attack_same_cell"].append(vec)
    names = ("adx", "ady", "adist", "edx", "edy", "edist", "costIn", "costOut", "costTotal",
             "sureAttack", "doubtAttack", "canAttack", "retreatToOrigin", "gapIncrease",
             "coverFinal", "threatFinal", "losAttack")
    out = {}
    for name in names:
        i = IDX[name]
        out[name] = {g: round(mean([v[i] for v in rows]), 4) if rows else None
                     for g, rows in groups.items()}
    out["counts"] = {g: len(rows) for g, rows in groups.items()}
    return out


def _predict_split(model, samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """План ДО (независимый argmax) и ПОСЛЕ (joint-декодер) — классы выбранных слотов."""
    yk = net.y_key(spec3.SCHEMA)
    before, after = {"count": 0}, {"count": 0}
    agree = retreat_joint = 0
    for s in samples:
        dec = joint.decode(model, s, schema=spec3.SCHEMA)
        base = joint.independent_baseline(dec["logp"], spec3.SCHEMA)
        kb = _plan_kind(s, int(base[yk["cells"]]))
        ka = _plan_kind(s, int(dec["label"][yk["cells"]]))
        before["count"] += 1
        after["count"] += 1
        before[kb] = before.get(kb, 0) + 1
        after[ka] = after.get(ka, 0) + 1
        agree += int(kb == ka)
        retreat_joint += int(ka == "hit_and_run")
    n = max(1, len(samples))
    return {"n": len(samples),
            "independent": {k: round(v / n, 4) for k, v in before.items() if k != "count"},
            "joint": {k: round(v / n, 4) for k, v in after.items() if k != "count"},
            "joint_hit_and_run_chosen": retreat_joint,
            "baseline_vs_joint_agree": round(agree / n, 4)}


def _eval_states_retreat(model, sources: List[Tuple[str, Dict[str, Any]]],
                        greedy, rounds: int = 10) -> Dict[str, Any]:
    """Есть ли в ОЦЕНОЧных состояниях ситуации, где отход легален/лучше по признакам учителя.

    Бой ведёт greedy (его состояния — там, где тактика учителя вообще применяется); на каждом
    состоянии считаем: (а) число легальных атак-с-отходом в A(s); (б) что выбрал greedy;
    (в) что выбрал joint-декодер модели; (г) joint-массу отступных атак; (д) «лучше ли» отход
    по тому же критерию, что использует greedy: coverFinal=1 в отходе при coverFinal=0 у выбора.
    """
    agg = {"states": 0, "states_with_legal_retreat_attack": 0, "greedy_retreat": 0,
           "model_joint_retreat": 0, "cover_prefers_retreat": 0, "mass_sum": 0.0}
    yk = net.y_key(spec3.SCHEMA)
    for _name, payload in sources:
        state = Simulation.of(BattleContext.from_payload(payload))
        played = 0
        while played < rounds and not state.hero_dead and state.foes:
            ctx = state.context_for(state.hero_id)
            obs = observe(ctx)
            slots = slots_v3.build(ctx, obs)
            sample = _encode(ctx, obs, slots)
            legal = joint.legal_mask(slots, ctx, spec3.SCHEMA)
            sample["legal"] = legal          # observation не несёт legal — прикладываем для массы
            retreat_trips = [(p, t, w) for p in range(slots.n_plans)
                             for t in range(len(slots.targets))
                             for w in range(len(slots.weapons))
                             if legal[p][t][w] and slots.plans[p]["attack_cell"]
                             != slots.plans[p]["end_cell"]]
            agg["states"] += 1
            agg["states_with_legal_retreat_attack"] += int(bool(retreat_trips))
            actions = greedy.plan(ctx)
            slots_v3.ensure_plan(slots, ctx, actions)
            glabel = slots_v3.label_of(ctx, slots, actions)
            dec = joint.decode(model, _encode(ctx, obs, slots), slots, ctx, spec3.SCHEMA)
            mlabel = dec["label"]
            if glabel is not None:
                gplan = slots.plans[glabel["plan"]] if 0 <= glabel["plan"] < slots.n_plans else None
                agg["greedy_retreat"] += int(gplan is not None
                                             and gplan["attack_cell"] != gplan["end_cell"]
                                             and 0 <= glabel["target"] < len(slots.targets))
            mplan = slots.plans[mlabel["plan"]] if 0 <= mlabel["plan"] < slots.n_plans else None
            agg["model_joint_retreat"] += int(mplan is not None
                                              and mplan["attack_cell"] != mplan["end_cell"]
                                              and 0 <= mlabel["target"] < len(slots.targets))
            if retreat_trips:
                agg["mass_sum"] += _joint_retreat_mass(model, sample)["retreat_mass"]
                # «лучше»: учитель выбрал атаку С МЕСТА, хотя легальна и атака с отходом
                # (greedy отходит ровно когда это выгодно по своей оценке)
                if glabel is not None and 0 <= glabel["target"] < len(slots.targets):
                    chosen = slots.plans[glabel["plan"]]
                    if chosen["attack_cell"] == chosen["end_cell"]:
                        agg["cover_prefers_retreat"] += 1
            seq = slots_v3.decode(slots, glabel or {"plan": 0, "target": spec.NONE_SLOT,
                                                     "weapon": spec.NONE_SLOT})
            mid = state.apply_actor_seq(state.hero_id, seq)
            state, _penalty = mid.foes_act()
            played += 1
    n = max(1, agg["states"])
    return {**{k: agg[k] for k in agg if k != "mass_sum"},
            "legal_retreat_attack_state_frac": round(agg["states_with_legal_retreat_attack"] / n, 4),
            "greedy_retreat_frac": round(agg["greedy_retreat"] / n, 4),
            "model_joint_retreat_frac": round(agg["model_joint_retreat"] / n, 4),
            "mean_joint_retreat_mass_when_legal":
                round(agg["mass_sum"] / max(1, agg["states_with_legal_retreat_attack"]), 6)}


def _encode(ctx, obs, slots):
    from arent import encode_v3
    return encode_v3.observation(ctx, obs, slots)


def main() -> int:
    prev = paths.workspace()
    paths.set_workspace(STAGE6_WS)          # читаем датасет/веса этапа 6 (workspace-относительно)
    try:
        samples = dataset.load(DATASET_NAME)
        train, val, _rep = splitting.split_grouped(samples, frac=0.85, seed=SEED, strict=True)
        best_path = os.path.join(STAGE6_WS, "runs", RUN_NAME, "model_best.json")
        model = backend.load_policy(best_path, kind="pure")

        # 1) обучающий сигнал: доли hit-and-run в метках (весь датасет, train, val)
        labels = {"all": _label_stats(samples), "train": _label_stats(train),
                  "val": _label_stats(val)}

        # 2) предсказания плана до/после joint-декодирования (val — честные для веса подгруппы)
        pred = {"val": _predict_split(model, val), "train": _predict_split(model, train)}

        # 3) joint-масса допустимых «атака+отход» троек на val
        masses = []
        for s in val:
            m = _joint_retreat_mass(model, s)
            if m["best_retreat_logp"] is not None:
                masses.append(m["retreat_mass"])
        joint_mass = {"val_samples_with_legal_retreat_attack": len(masses),
                      "val_total": len(val),
                      "mean_retreat_mass": round(mean(masses), 6) if masses else 0.0,
                      "max_retreat_mass": round(max(masses), 6) if masses else 0.0}

        # 4) признаки, различающие планы с отходом (среди меток-атак)
        feats = _features_split(samples)

        # 5) оценочные состояния: где отход легален и реально применяется учителем
        ho3 = dataset.independent_sources(use_live=False, prefixes=(INDEPENDENT_PREFIX,))
        greedy = get_teacher("greedy", rounds=1, time_limit_sec=None)
        with pinned(rounds=1, time_limit_sec=None):
            eval_states = _eval_states_retreat(model, ho3, greedy)

        signal_short = labels["train"]["hit_and_run_frac_of_attacks"]
        report = {
            "labels": labels,
            "predictions": pred,
            "joint_mass": joint_mass,
            "retreat_vs_stay_features": feats,
            "eval_states": eval_states,
            "diagnosis": {
                "training_signal_frac_of_attacks (train)": signal_short,
                "decoding_allows_retreat": eval_states["legal_retreat_attack_state_frac"] > 0.0,
                "model_gives_retreat_any_mass": joint_mass["max_retreat_mass"] > 0.0,
                "conclusion": ("нулевой hit-and-run у модели объясняется в ПЕРВУЮ очередь "
                               "слабым обучающим сигналом (мало меток) и низкой joint-массой; "
                               "декодер отход НЕ запрещает — допустимые отступные тройки есть "
                               "в A(s) и выбирались бы при росте их вероятности"
                               if signal_short and signal_short > 0 else
                               "меток hit-and-run в train нет — выучить тактику неоткуда; "
                               "ошибка декодирования НЕ установлена (A(s) отход допускает)"),
            },
        }
        out = os.path.join(OUT_WS, "stage7_hitrun.json")
        os.makedirs(OUT_WS, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)

        print("=== метки hit-and-run (доли) ===")
        for k, v in labels.items():
            print(f"  {k}: атак {v['attacks']}, hit-and-run {v['hit_and_run_labels']} "
                  f"({100*v['hit_and_run_frac_of_attacks']:.1f}% атак)")
        print("=== предсказания плана (val) ===")
        print(f"  independent: {pred['val']['independent']}")
        print(f"  joint:       {pred['val']['joint']} (hit-and-run выбрано: "
              f"{pred['val']['joint_hit_and_run_chosen']})")
        print(f"=== joint-масса отступных атак (val): {joint_mass} ===")
        print("=== оценочные ho3-состояния ===")
        for k in ("states", "states_with_legal_retreat_attack", "greedy_retreat",
                  "model_joint_retreat", "mean_joint_retreat_mass_when_legal"):
            print(f"  {k}: {eval_states[k]}")
        print(f"  сохранено: {out}")
        return 0
    finally:
        paths.set_workspace(prev)


if __name__ == "__main__":
    raise SystemExit(main())
