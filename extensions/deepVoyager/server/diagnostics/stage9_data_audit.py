# diagnostics/stage9_data_audit.py — ЭТАП 9, часть A: фактические данные и целевое поведение.
#
# Только ЧИТАЕМ существующее: stage6_v3.jsonl (копия в stage8_out тот же байт-в-байт),
# манифест этапа 6 и weights stage8_bc_smoke/model_best.json. Ничего не переобучаем.
#
# Отвечаем на 5 вопросов:
#  A1 число независимых сценариев (meta.arena), состояний (state_signature без метки),
#     уникальных действий (канонические тройки), повторов одного состояния (двойная
#     разметка greedy+battlecast);
#  A2 распределение меток: атака/без-атаки, hit-and-run (move ПОСЛЕ use), подход, оружие,
#     размер/роль — из meta.actions; богатство A(s) (|A(s)|, боевые тройки, «есть выбор»);
#  A3 неоднозначные метки: один state_signature — разные канонические тройки; стабильность;
#  A4 может ли модель превзойти учителя на ЭТИХ данных: сравнение на val — model joint
#     decode vs метка, константный majority-baseline, teacher-vs-teacher agreement
#     (потолок согласованности цели: смешанные метки двух учителей — не одна функция);
#  A5 отражает ли метка фокус-огонь/выживание: агрегаты манифеста этапа 6 (nearest/killable
#     доли) + что из этого следует для одноходового учителя.
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))     # server/
sys.path.insert(0, _HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from arent import backend, dataset, joint, paths, scores, splitting, spec3

SERVER = os.path.dirname(_HERE)
STAGE6_WS = os.path.join(SERVER, "stage6_out")
STAGE8_WS = os.path.join(SERVER, "stage8_out")
OUT_WS = os.path.join(SERVER, "stage9_out")
DATASET_NAME = "stage6_v3"
MODEL_BEST = os.path.join(STAGE8_WS, "runs", "stage8_bc_smoke", "model_best.json")


def _label_triple(sample: Dict[str, Any]):
    return joint.ensure_jointly_legal(sample, spec3.SCHEMA)


def _action_shape(sample: Dict[str, Any]) -> str:
    """Форма плана учителя по порядку действий: stay / approach / attack / hit-and-run.

    Ровно логика stage6_common._tags: move ДО use — подход, move ПОСЛЕ use — уход.
    Атака = наличие use. Без геометрии: только порядок действий из meta.actions.
    """
    acts = (sample.get("meta") or {}).get("actions") or []
    used = False
    after_move = False
    any_move = False
    for a in acts:
        kind = a.get("action")
        if kind == "use":
            used = True
        elif kind == "move":
            any_move = True
            if used:
                after_move = True
    if used:
        return "hit_and_run" if after_move else "attack"
    return "approach" if any_move else "stay"


def a1_a2_a3(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    arenas = Counter(str((s.get("meta") or {}).get("arena")) for s in samples)
    sigs: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in samples:
        sigs[splitting.state_signature(s)].append(s)
    yset = Counter(_label_triple(s) for s in samples)
    shapes = Counter(_action_shape(s) for s in samples)
    # A2: богатство A(s)
    legal_counts, attack_states, multi_attack, choice_states = [], 0, 0, 0
    for s in samples:
        legal = s["legal"]
        n_legal = sum(sum(sum(row) for row in plane) for plane in legal)
        none_w = joint.NONE_WEAPON
        none_t = joint.NONE_TARGET
        no_attack = sum(legal[p][none_t][none_w] for p in range(len(legal)))
        attacks = n_legal - no_attack
        legal_counts.append(n_legal)
        attack_states += int(attacks > 0)
        multi_attack += int(attacks > 1)
        choice_states += int(attacks > 1 and no_attack > 0)   # «есть тактический выбор»
    lc = Counter(legal_counts)
    # A3: состояния с неоднозначной разметкой (один state_signature — разные тройки)
    dup_states = {k: v for k, v in sigs.items() if len(v) > 1}
    ambiguous, stable_dups = 0, 0
    amb_examples = []
    for k, group in dup_states.items():
        triples = {_label_triple(s) for s in group}
        if len(triples) > 1:
            ambiguous += 1
            if len(amb_examples) < 5:
                amb_examples.append({"state_sig": k[:12], "labels": [list(t) for t in triples],
                                     "shapes": sorted({_action_shape(s) for s in group})})
        else:
            stable_dups += 1
    # доли none-target/none-weapon в метках (оружие: слот NONE == «без атаки»)
    none_w = sum(1 for _p, _t, w in yset.elements() if w == joint.NONE_WEAPON)
    return {
        "examples": len(samples),
        "scenarios_unique_arenas": len(arenas),
        "samples_per_arena": {k: v for k, v in arenas.most_common()},
        "states_unique_signatures": len(sigs),
        "repeated_states": len(dup_states),
        "repeated_state_rows": sum(len(v) for v in dup_states.values()),
        "unique_canonical_actions": len(yset),
        "top_actions": {str(k): v for k, v in yset.most_common(10)},
        "action_shapes": dict(shapes),
        "labels_noattack": int(none_w),
        "labels_attack": len(samples) - int(none_w),
        "As_size_hist": {str(k): v for k, v in sorted(lc.items())},
        "As_size_min": min(legal_counts), "As_size_max": max(legal_counts),
        "As_size_mean": round(sum(legal_counts) / len(legal_counts), 2),
        "states_with_attack_option": attack_states,
        "states_with_2plus_attacks": multi_attack,
        "states_with_real_choice": choice_states,
        "ambiguous_states": ambiguous, "ambiguous_share_of_repeated": round(
            ambiguous / max(1, len(dup_states)), 3),
        "stable_duplicate_states": stable_dups,
        "ambiguity_examples": amb_examples,
    }


def a4_ceiling(samples: List[Dict[str, Any]], model) -> Dict[str, Any]:
    """Потолок BC на этих данных: модель vs метка, мажоритарный baseline, teacher-vs-teacher."""
    train_set, val, _rep = splitting.split_grouped(samples, frac=0.85, seed=20261022,
                                                   strict=True)
    m = scores.metrics(model, val)
    # константный baseline: самая частая каноническая тройка ВСЕЙ выборки
    mode_triple, mode_n = Counter(_label_triple(s) for s in train_set).most_common(1)[0]
    mode_acc = sum(1 for s in val if _label_triple(s) == mode_triple) / max(1, len(val))
    # «метка без атаки» в val: каноническая тройка с NONE-целью и NONE-оружием
    na_acc = sum(1 for s in val
                 if _label_triple(s)[1] == joint.NONE_TARGET
                 and _label_triple(s)[2] == joint.NONE_WEAPON) / max(1, len(val))
    # teacher-vs-teacher: согласованность на повторных состояниях
    sigs: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in samples:
        sigs[splitting.state_signature(s)].append(s)
    pairs = [g for g in sigs.values() if len(g) == 2]
    agree = sum(1 for g in pairs if _label_triple(g[0]) == _label_triple(g[1]))
    # NLL метки vs NLL АЛЬТЕРНАТИВНОЙ метки учителя на неоднозначных состояниях
    amb_nll = []
    for g in sigs.values():
        if len(g) < 2:
            continue
        t1, t2 = _label_triple(g[0]), _label_triple(g[1])
        if t1 == t2:
            continue
        nll_own = scores.sample_joint_nll(model, g[0])
        flipped = dict(g[0], y={"plan": t2[0], "target": t2[1] if t2[1] < joint.NONE_TARGET
                                else -1, "weapon": t2[2] if t2[2] < joint.NONE_WEAPON else -1})
        try:
            nll_alt = scores.sample_joint_nll(model, flipped)
            amb_nll.append((round(nll_own, 3), round(nll_alt, 3)))
        except Exception:
            pass
    return {
        "split": {"train": len(train_set), "val": len(val)},
        "model_val": {"joint_nll": m["joint_nll"],
                      "joint_decode_accuracy": m["joint_decode_accuracy"],
                      "independent_baseline_accuracy": m["independent_baseline_accuracy"]},
        "majority_const_baseline_acc": round(mode_acc, 3),
        "majority_const_triple": list(mode_triple), "majority_n": mode_n,
        "noattack_label_share_val": round(na_acc, 3),
        "teacher_pair_agreement": {
            "pairs": len(pairs), "agree": agree,
            "agree_frac": round(agree / max(1, len(pairs)), 3),
            "note": "пара = одно состояние, размеченное ДВУМЯ учителями (greedy/battlecast); "
                    "несогласие — верхняя граница консистентности цели BC"},
        "model_prefers_own_teacher_label_on_disagreements": {
            "count": len(amb_nll),
            "own_lower_nll": sum(1 for a, b in amb_nll if a < b),
            "pairs": amb_nll[:8]},
    }


def main() -> int:
    os.makedirs(OUT_WS, exist_ok=True)
    prev = paths.workspace()
    paths.set_workspace(STAGE6_WS)              # читаем боевой датасет этапа 6 (без записи)
    try:
        samples = dataset.load(DATASET_NAME)
    finally:
        paths.set_workspace(prev)
    model = backend.load_policy(MODEL_BEST, kind="pure")   # веса этапа 8, только чтение
    part = a1_a2_a3(samples)
    ceil = a4_ceiling(samples, model)
    manifest_path = os.path.join(STAGE6_WS, "stage6_dataset_manifest.json")
    a5 = {}
    if os.path.exists(manifest_path):
        man = json.load(open(manifest_path, encoding="utf-8"))
        a5 = {"from_stage6_manifest": {
            "attacks_vs_noattack": man["label_distributions"]["attacks_vs_noattack"],
            "weapon_types": man["label_distributions"]["weapon_types"],
            "target_selection": man["label_distributions"]["target_selection"],
            "team_and_role": man["label_distributions"]["team_and_role"]},
            "reading": "целевая метка — ОДНОХОДОВЫЙ оптумум учителя (greedy 1 раунд, "
                       "battlecast с коротким look-ahead): nearest/killable доли показывают, "
                       "насколько она вообще похожа на фокус-огонь и заботу о выживании"}
    report = {"part_A": part, "ceiling": ceil, "tactics_alignment": a5}
    out = os.path.join(OUT_WS, "stage9_data_audit.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps({"A1": {k: part[k] for k in ("examples", "scenarios_unique_arenas",
                                                  "states_unique_signatures",
                                                  "repeated_states",
                                                  "unique_canonical_actions")},
                      "A2_shapes": part["action_shapes"],
                      "A2_As": {"min": part["As_size_min"], "mean": part["As_size_mean"],
                                "max": part["As_size_max"],
                                "real_choice": part["states_with_real_choice"]},
                      "A3": {"ambiguous": part["ambiguous_states"],
                             "stable": part["stable_duplicate_states"],
                             "share": part["ambiguous_share_of_repeated"]},
                      "A4": {"decode_acc": ceil["model_val"]["joint_decode_accuracy"],
                             "majority": ceil["majority_const_baseline_acc"],
                             "teacher_agree_frac":
                                 ceil["teacher_pair_agreement"]["agree_frac"]}},
                     ensure_ascii=False, indent=1))
    print(f"сохранено: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
