# arent/teacher_bench.py — гонка внешних политик-учителей Фазы A (A3) поверх abset-harnessа.
#
# Что меряем: battlecast_baseline (честный алиас battlecast) против ja2_positioning
# (осторожный позиционный профиль) на СТРУКТУРНОМ генераторе «1-4 на 1-4»:
#   • stage43_canon — честная сравнимая «линейка» (симметричные NvN, structured) для вердикта;
#   • stage43_pool  — обучающий пул (все 1..4 + численная асимметрия, random_start) для полноты.
# Оба прогона на ОДНОМ seed и ОДНОМ бюджете => разность метрик честна (парный bootstrap CI).
#
# ЧЕСТНО про смысл: Фаза A — ИНФРАСТРУКТУРА измерений, а не заявление «ja2 сильнее». Эта гонка
# проверяет, что harness различает профили и воспроизводим (fingerprint набора стабилен).
# Настоящее усиление battlecast (evaluate_plan/focus-fire) и реальные стили — Фазы B/C по PLAN.md.
import json
import os
from typing import Any, Dict, Optional, Sequence

from arent import abset, paths

# Артефакт живёт в дереве исходников (не в рабочем каталоге данных): search_teacher/bench/.
_BENCH_DIR = os.path.join(os.path.dirname(paths.source_dir()), "search_teacher", "bench")

# Что показываем в своде на учителя (берётся из abset._agg): честные измеряемые метрики боя.
_SUMMARY_KEYS = ("clear_rate", "survival_rate", "mean_rounds", "mean_rollout",
                 "dmg_per_action", "kill_rate", "wasted_rate")
# Головные разности A−B (уже с bootstrap CI из abset.paired), чтобы вердикт читался сразу.
_HEADLINE = ("rollout", "dmg_net", "cleared", "survived", "kills", "wasted")


def _summary_one(report: Dict[str, Any]) -> Dict[str, Any]:
    """Свод по одному abset-прогону: метрики каждой политики + головные разности A−B."""
    per = {name: {k: report["per_teacher"][name].get(k) for k in _SUMMARY_KEYS}
           for name in report["teachers"]}
    diff = {m: report["paired"]["diff_stats"].get(m) for m in _HEADLINE}
    return {"n_scenes": report["n_scenes"], "set_fingerprint": report["set_fingerprint"],
            "a_minus_b": report["a_minus_b"], "per_teacher": per, "diff_a_minus_b": diff}


def race(teachers: Sequence[str] = ("battlecast_baseline", "ja2_positioning"),
         seed: int = 20261020, canon_each: int = 2, pool_each: int = 1,
         cap: Optional[int] = None, rounds: int = 8, teacher_rounds: int = 1,
         ci_seed: int = 1234) -> Dict[str, Any]:
    """Прогон учителей на каноне и на учебном пуле (один seed/бюджет); собрать один отчёт.

    canon_each/pool_each — сцен на пару у stage43-генераторов; cap срезает итоговый набор
    (детерминированно) для ограниченной по стоимости гонки. Вердикт читаем в summary.
    """
    t = tuple(teachers)
    canon = abset.run(count=canon_each, seed=seed, rounds=rounds, teacher_rounds=teacher_rounds,
                      teachers=t, ci_seed=ci_seed, source="stage43_canon", cap=cap)
    pool = abset.run(count=pool_each, seed=seed, rounds=rounds, teacher_rounds=teacher_rounds,
                     teachers=t, ci_seed=ci_seed, source="stage43_pool", cap=cap)
    return {"schema": "ext_race_v1", "teachers": list(t), "set_seed": seed,
            "rounds_cap": rounds, "teacher_rounds": teacher_rounds, "ci_seed": ci_seed,
            "cap": cap, "summary": {"canon": _summary_one(canon), "pool": _summary_one(pool)},
            "canon": canon, "pool": pool}


def write(report: Dict[str, Any], out_dir: Optional[str] = None,
          name: str = "baseline_vs_ja2.json") -> str:
    """Пишет отчёт гонки в JSON (по умолчанию search_teacher/bench/); возвращает путь."""
    directory = out_dir or _BENCH_DIR
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, sort_keys=True)
    return path


def _print_summary(report: Dict[str, Any]) -> None:
    """Человекочитаемая таблица вердикта (для CLI/принта), без дампа всего JSON."""
    for src in ("canon", "pool"):
        s = report["summary"][src]
        print(f"\n=== {src} (сцен {s['n_scenes']}, fingerprint {s['set_fingerprint'][:12]}, "
              f"{s['a_minus_b']}) ===")
        cols = ("clear_rate", "survival_rate", "mean_rounds", "mean_rollout",
                "dmg_per_action", "kill_rate", "wasted_rate")
        print("политика".ljust(22) + "".join(c[:10].rjust(12) for c in cols))
        for name in report["teachers"]:
            row = s["per_teacher"][name]
            print(name.ljust(22) + "".join(f"{row.get(c)!s:>12}" for c in cols))
        print("разность A-B (mean, CI_lo..CI_hi), где CI не накрывает 0 - сдвиг заметен:")
        for m, st in s["diff_a_minus_b"].items():
            if st and st.get("mean") is not None:
                flag = " *" if not (st["ci_lo"] <= 0 <= st["ci_hi"]) else ""
                print(f"  {m:<10} {st['mean']:>8.3f}  [{st['ci_lo']:.3f}, {st['ci_hi']:.3f}]{flag}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI: python -m arent.teacher_bench [--canon-each 4 --pool-each 2 --out ...] [--json]."""
    import argparse
    ap = argparse.ArgumentParser(prog="arent.teacher_bench", description=__doc__)
    ap.add_argument("--teachers", nargs="*", default=["battlecast_baseline", "ja2_positioning"])
    ap.add_argument("--seed", type=int, default=20261020)
    ap.add_argument("--canon-each", type=int, default=2, help="сцен на пару в каноне")
    ap.add_argument("--pool-each", type=int, default=1, help="сцен на пару в пуле")
    ap.add_argument("--cap", type=int, default=None, help="срезать итоговый набор (det.)")
    ap.add_argument("--rounds", type=int, default=8, help="потолок раундов closed-loop")
    ap.add_argument("--out", default=None, help="куда писать JSON (по умолчанию bench/)")
    ap.add_argument("--json", action="store_true", help="дампнуть полный отчёт в stdout")
    args = ap.parse_args(list(argv) if argv is not None else None)
    report = race(teachers=tuple(args.teachers), seed=args.seed, canon_each=args.canon_each,
                  pool_each=args.pool_each, cap=args.cap, rounds=args.rounds)
    path = write(report, args.out) if args.out else write(report)
    _print_summary(report)
    print(f"\nартефакт -> {path}")
    if args.json:
        print(json.dumps(report["summary"], ensure_ascii=False, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":                              # pragma: no cover - CLI-точка
    raise SystemExit(main())
