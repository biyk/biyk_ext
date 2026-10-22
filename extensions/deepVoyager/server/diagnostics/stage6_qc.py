# diagnostics/stage6_qc.py — ЭТАП 6 (часть 3): полный QC малой v3-выборки (абс + доли).
#
# Проверяем НЕ «тест зелёный», а числа, по которым видно перекос: атаки/без-атаки, планы с
# attack_cell==end_cell против «атака→уход», типы оружия, близость и добиваемость целей,
# размеры команд и роли, уникальные сцены/состояния, групповой train/val split БЕЗ пересечений,
# доля меток в A(s), частота пропусков по этапам. Разделения считает arent.splitting по
# meta.arena (группа=сценарий), с точным дедупом состояний union-find'ом.
import os
import sys
from collections import Counter
from typing import Any, Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))     # server/
sys.path.insert(0, _HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from arent import splitting                       # noqa: E402
from arent.splitting import state_signature      # noqa: E402
from stage6_common import build_records, classify, SEED   # noqa: E402


def combine_teachers(teachers=("greedy", "battlecast"), scen_count=12, per_src=6,
                     rounds_max=3, seed=SEED):
    """Собрать records обоих учителей; точные дубли (state+метка) схлопнуть одним state_key.

    Возвращает (records, accounting_per_teacher). Дедуп по dataset.state_key (включает y):
    identical rows не удваиваются, а разная разметка одного состояния остаётся обе.
    """
    from arent.dataset import state_key
    seen, records, acct = set(), [], {}
    for t in teachers:
        recs, skips, states = build_records(t, scen_count, per_src, rounds_max, seed)
        acct[t] = classify(t, recs, skips, states, seed=seed, per_src=per_src,
                           rounds_max=rounds_max)
        for r in recs:
            key = state_key(r["sample"])
            if key in seen:
                continue
            seen.add(key)
            r["tags"]["teacher"] = t
            records.append(r)
    return records, acct


def _dist(values) -> Dict[str, int]:
    return {str(k): v for k, v in Counter(values).most_common()}


def qc_tables(records: List[Dict[str, Any]], split_report: Dict[str, Any],
              accounting: Dict[str, Any]) -> Dict[str, Any]:
    n = len(records)
    tg = [r["tags"] for r in records]
    attacks = [t for t in tg if t["is_attack"]]
    noatks = [t for t in tg if not t["is_attack"]]
    na = max(1, len(attacks))
    # доля меток в A(s): по A(s)-проверке из classify (attack_in_As+noattack_in_As)/(по всем matched)
    tot_matched = sum(a["matched_to_plan"] for a in accounting.values()) or 1
    tot_in = sum(a["attack_in_As"] + a["noattack_in_As"] for a in accounting.values())
    tot_out = sum(a["attack_out_As"] + a["noattack_out_As"] for a in accounting.values())
    return {
        "records_total": n,
        "attacks_vs_noattack": {
            "attack": len(attacks), "attack_frac": round(len(attacks) / n, 4),
            "no_attack": len(noatks), "no_attack_frac": round(len(noatks) / n, 4)},
        "plan_cell_geometry": {
            # среди атакующих: удар с места (attack==end) против hit-and-run (attack!=end)
            "attack_same_cell": sum(1 for t in attacks if t["same_cell"]),
            "attack_retreat": sum(1 for t in attacks if t["retreat"]),
            "attack_retreat_frac_of_attacks": round(
                sum(1 for t in attacks if t["retreat"]) / na, 4),
            "all_same_cell": sum(1 for t in tg if t["same_cell"]),
            "all_retreat": sum(1 for t in tg if t["retreat"])},
        "weapon_types": _dist(t.get("weapon", "none") for t in tg),
        "target_selection": {
            "attacked_with_target": sum(1 for t in attacks if "target_is_nearest" in t),
            "nearest": sum(1 for t in attacks if t.get("target_is_nearest")),
            "non_nearest": sum(1 for t in attacks if t.get("target_is_nearest") is False),
            "non_nearest_frac": round(
                sum(1 for t in attacks if t.get("target_is_nearest") is False)
                / max(1, sum(1 for t in attacks if "target_is_nearest" in t)), 4),
            "killable": sum(1 for t in attacks if t.get("target_killable")),
            "killable_frac": round(
                sum(1 for t in attacks if t.get("target_killable")) / na, 4)},
        "team_and_role": {
            "team_sizes": _dist(f"{t['allies']}v{t['enemies']}" for t in tg),
            "ally_count": _dist(t["allies"] for t in tg),
            "enemy_count": _dist(t["enemies"] for t in tg),
            "roles": _dist(t.get("role", "?") for t in tg)},
        "uniqueness": {
            "unique_scenarios": len({t["arena"] for t in tg}),
            "unique_states": len({state_signature(r["sample"]) for r in records})},
        "split": split_report,
        "admissibility": {
            "matched_all_teachers": tot_matched, "in_As": tot_in, "out_As": tot_out,
            "frac_in_As": round(tot_in / tot_matched, 4)},
        "per_teacher_accounting": accounting,
    }


def _pct(x: float) -> str:
    return f"{100.0 * x:.1f}%"


def _print(tables: Dict[str, Any]) -> None:
    n = tables["records_total"]
    av = tables["attacks_vs_noattack"]
    pg = tables["plan_cell_geometry"]
    ts = tables["target_selection"]
    ad = tables["admissibility"]
    sp = tables["split"]
    print(f"=== QC малой v3-выборки (примеров всего: {n}) ===")
    print(f"  атаки: {av['attack']} ({_pct(av['attack_frac'])}) | "
          f"без атаки: {av['no_attack']} ({_pct(av['no_attack_frac'])})")
    print(f"  планы атаки: с места (attack==end) {pg['attack_same_cell']} | "
          f"hit-and-run (attack!=end) {pg['attack_retreat']} "
          f"({_pct(pg['attack_retreat_frac_of_attacks'])} от атак)")
    print(f"  все примеры: same_cell {pg['all_same_cell']} | retreat {pg['all_retreat']}")
    print(f"  типы оружия: {tables['weapon_types']}")
    print(f"  цели: ближайшая {ts['nearest']} | НЕ ближайшая {ts['non_nearest']} "
          f"({_pct(ts['non_nearest_frac'])}); добиваемых {ts['killable']} "
          f"({_pct(ts['killable_frac'])})")
    print(f"  размеры команд (allies v enemies): {tables['team_and_role']['team_sizes']}")
    print(f"  роли: {tables['team_and_role']['roles']}")
    print(f"  уникальных сценариев: {tables['uniqueness']['unique_scenarios']}; "
          f"уникальных состояний: {tables['uniqueness']['unique_states']}")
    print(f"  меток в A(s): {ad['in_As']}/{ad['matched_all_teachers']} "
          f"({_pct(ad['frac_in_As'])}); вне A(s): {ad['out_As']}")
    print(f"  split: групп всего={sp['groups_total']}, train-групп={sp['train_groups']}, "
          f"val-групп={sp['val_groups']}, train-примеров={sp['train_samples']}, "
          f"val-примеров={sp['val_samples']}")
    print(f"  ПЕРЕСЕЧЕНИЯ: групп={sp['group_overlap'] or 'НЕТ'}, "
          f"состояний={sp['exact_state_overlap'] or 'НЕТ'}, warnings={sp['warnings'] or 'нет'}")
    print("  учёт по учителям (пропуски/ошибки по этапам):")
    for t, a in tables["per_teacher_accounting"].items():
        print(f"    {t}: состояний={a['states_received']}, размечено={a['matched_to_plan']}, "
              f"пропуски={a['skip_reasons']}, внеA(s)={a['attack_out_As'] + a['noattack_out_As']}")


def main() -> int:
    records, accounting = combine_teachers()
    samples = [r["sample"] for r in records]
    train, val, report = splitting.split_grouped(samples, frac=0.85, seed=SEED, strict=True)
    report["train_arenas"] = sorted({str((s.get('meta') or {}).get('arena')) for s in train})
    report["val_arenas"] = sorted({str((s.get('meta') or {}).get('arena')) for s in val})
    tables = qc_tables(records, report, accounting)
    _print(tables)
    # жёсткие стоп-условия QC: ни одной метки вне A(s), пересечений сплита нет, доли посчитаны
    ok = (tables["admissibility"]["out_As"] == 0 and not report["group_overlap"]
          and not report["exact_state_overlap"])
    import json
    out = os.path.join(_HERE, "stage6_qc.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(tables, f, ensure_ascii=False, indent=1)
    print(f"  сохранено: {out}  |  QC OK={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
