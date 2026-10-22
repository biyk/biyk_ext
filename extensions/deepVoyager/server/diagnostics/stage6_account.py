# diagnostics/stage6_account.py — ЭТАП 6 (1.1): запустить учёт для обоих учителей и свести числа.
#
# Печатает воронку по каждому учителю и парный итог, проверяя, что все уровни сходятся.
# Именно здесь расхождение «186 состояний × 2 учителя vs greedy 135 / battlecast 100» либо
# подтверждается как подмена знаменателя (135/100 — это ПОДМНОЖЕСТВО атакующих меток, а не все
# примеры), либо вскрывается как реальная потеря данных. Ничего не отбрасываем молча.
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))     # server/ (чтобы import arent/playground)
sys.path.insert(0, _HERE)                       # diagnostics/ (stage6_common)
try:
    sys.stdout.reconfigure(encoding="utf-8")     # Windows cp1251 не печатает рамочные символы
except Exception:
    pass
from stage6_common import account_teacher      # noqa: E402

OUT = os.path.join(_HERE, "stage6_accounting.json")


def _fmt(res: dict) -> str:
    lines = [
        f"=== учитель {res['teacher']} (seed={res['seed']}, per_src={res['per_src']}, "
        f"rounds_max={res['rounds_max']}) ===",
        f"  источников: сценариев={res['sources']['scenarios']}, арен={res['sources']['arenas']}",
        f"  состояний получено ............... {res['states_received']}",
        f"    ├─ не сформировал действие (нет оружия/цели) {res['labels_no_attack_state']}",
        f"    └─ сформировал действие .......... {res['teacher_formed_action']}",
        f"        ├─ размечено (roundtrip ok) ..... {res['matched_to_plan']}",
        f"        │     ├─ атакующих меток ....... {res['attack_labels']} "
        f"(в A(s)={res['attack_in_As']}, вне={res['attack_out_As']})",
        f"        │     └─ меток без атаки ....... {res['noattack_labels']} "
        f"(в A(s)={res['noattack_in_As']}, вне={res['noattack_out_As']})",
        f"        └─ не размечено .............. "
        f"{res['unmatched']['no_slots'] + res['unmatched']['label_out_of_slots'] + res['unmatched']['roundtrip_mismatch']} "
        f"(no_slots={res['unmatched']['no_slots']}, "
        f"label_out={res['unmatched']['label_out_of_slots']}, "
        f"roundtrip={res['unmatched']['roundtrip_mismatch']})",
        f"  групп (уникальных арен) .......... {res['groups']}",
        f"  причины пропусков ................ {res['skip_reasons']}",
        f"  СХОДИМОСТЬ: states={res['check_states']} formed={res['check_formed']} "
        f"split={res['check_matched_split']} attackA={res['check_attack_As']} "
        f"noattackA={res['check_noattack_As']}",
    ]
    return "\n".join(lines)


def main() -> int:
    results = [account_teacher(t) for t in ("greedy", "battlecast")]
    for r in results:
        print(_fmt(r))
        print()
    g, b = results
    all_checks = all(bool(r[k]) for r in results for k in r if k.startswith("check_"))
    print("=== парный итог ===")
    print(f"  greedy:     состояний={g['states_received']}, примеров={g['matched_to_plan']} "
          f"(атака={g['attack_labels']}, без-атаки={g['noattack_labels']}), "
          f"меток вне A(s)={g['attack_out_As'] + g['noattack_out_As']}")
    print(f"  battlecast: состояний={b['states_received']}, примеров={b['matched_to_plan']} "
          f"(атака={b['attack_labels']}, без-атаки={b['noattack_labels']}), "
          f"меток вне A(s)={b['attack_out_As'] + b['noattack_out_As']}")
    print(f"  ВСЕ воронки сходятся: {all_checks}")
    print("  знаменатель: 'атакующих меток' — ПОДМНОЖЕСТВО примеров, а не все примеры; "
          "примеры без атаки легитимны и не считаются отказом.")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"results": results, "all_checks_pass": all_checks}, f,
                  ensure_ascii=False, indent=1)
    print(f"  сохранено: {OUT}")
    return 0 if all_checks and (g["attack_out_As"] + g["noattack_out_As"] == 0
                                and b["attack_out_As"] + b["noattack_out_As"] == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
