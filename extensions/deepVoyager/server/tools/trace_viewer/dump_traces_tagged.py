# tools/trace_viewer/dump_traces_tagged.py — дамп трейсов С as-if-тегами (record_only-счётчики).
#
# Зачем: .ray/dump_traces.py пишет дамп с counters=None -> в reward_breakdown теги всегда null,
# и вьюер не показывает ни as-if-разбор, ни ссылки на теги. Здесь ТО же самое, но
# counters=Counters(): fight_teams обвешивает среду TacticsShaper(record_only=True) —
# награда остаётся честным исходом (§1.1, ничего не течёт в reward), а каждый шаг получает
# last_diag={fired,violated,weights,field,asif} в reward_breakdown.tags.
#
# Изоляция: чужой .ray/dump_traces.py НЕ правится — только импортируем его хелперы
# (resolve_checkpoint/load_cpu/build_sources) и свой collect-цикл с counters.
# Только ЧТЕНИЕ чекпойнта + бои (CPU/GPU по наличию); ничего не обучает.
#
# Запуск (из server\):
#   $env:PYTHONPATH=(Get-Location).Path
#   & ".\arent\.venv\Scripts\python.exe" ".\tools\trace_viewer\dump_traces_tagged.py" [run] [опции]
# Выход: .ray/traces_all_<run>_tagged.json — как у dump_traces.py (вкл. row["arena"] с размерами
# поля scene/walls/tokens) + заполненные reward_breakdown.tags.
import argparse
import datetime as dt
import json
import os
import sys
from typing import List

HERE = os.path.dirname(os.path.abspath(__file__))                  # .../server/tools/trace_viewer
SERVER = os.path.dirname(os.path.dirname(HERE))                     # .../server
sys.path.insert(0, SERVER)
sys.path.insert(0, os.path.join(SERVER, ".ray"))                    # чтобы import dump_traces

import dump_traces as base                                           # noqa: E402
from arent import team_eval                                          # noqa: E402
from arent.tactics_counters import Counters                          # noqa: E402


def collect_rows_tagged(model, opponents: List[str], sources, rounds_cap: int,
                        count_each_label: str = "") -> List[dict]:
    """Как dump_traces.collect_rows, НО с counters=Counters() (record_only-теги в каждом шаге)."""
    rows: List[dict] = []
    for opp in opponents:
        counters = Counters()                                       # свой набор счётчиков на соперника
        got = team_eval.matchup_sources(model, opp, sources, rounds_cap=rounds_cap, draw_window=4,
                                        swap_sides=True, openings=True, rich_trace=True,
                                        shape_stage="stage3", trace_limit=0, counters=counters)
        tagged = sum(1 for r in got for st in r["trace"]
                     if (st.get("reward_breakdown") or {}).get("tags"))
        print("[battles] %s vs %s: %d боёв | шагов с тегами: %d"
              % (model.name, opp, len(got), tagged), flush=True)
        rows.extend(got)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Dump ALL-battle traces WITH as-if tags (record_only).")
    ap.add_argument("run", nargs="?", default=None,
                    help="run name (arent/runs/<run>/model.json); пусто -> freshest")
    ap.add_argument("--max-battles", type=int, default=0, help="0 (default) = dump every battle")
    ap.add_argument("--count-each", type=int, default=2, help="scenes per ordered pair")
    ap.add_argument("--seed", type=int, default=133)
    ap.add_argument("--rounds-cap", type=int, default=8)
    ap.add_argument("--opponents", default="greedy,battlecast", help="csv of opponent names")
    ap.add_argument("--out", default=None,
                    help="override output path (default .ray/traces_all_<run>_tagged.json)")
    a = ap.parse_args()

    path = base.resolve_checkpoint(a.run)
    run_name = a.run or os.path.basename(os.path.dirname(path))
    opponents = [s.strip() for s in a.opponents.split(",") if s.strip()]

    model = base.load_cpu(path, run_name)
    sources, arenas = base.build_sources(a.count_each, a.seed)   # dump_traces (14:10) возвращает и арены
    rows = collect_rows_tagged(model, opponents, sources, a.rounds_cap)
    for r in rows:                                    # как в dump_traces.py: вшить арену в каждый бой
        r["arena"] = arenas.get(r["name"])
    if a.max_battles and a.max_battles > 0:
        rows = rows[:a.max_battles]

    payload = {"run": run_name, "generated": dt.datetime.now().isoformat(timespec="seconds"),
               "model": path, "counters": "record_only(as-if tags)", "rows": rows}
    out_path = a.out or os.path.join(SERVER, ".ray", "traces_all_%s_tagged.json" % run_name)
    with open(out_path, "w", encoding="utf-8") as f:                # прямой UTF-8: без mojibake
        json.dump(payload, f, ensure_ascii=False, indent=1, default=base._json_default)

    tally: dict = {}
    tag_steps = tot_steps = 0
    for r in rows:
        tally[r["outcome"]] = tally.get(r["outcome"], 0) + 1
        for st in r["trace"]:
            tot_steps += 1
            if (st.get("reward_breakdown") or {}).get("tags"):
                tag_steps += 1
    print("[done] %d боёв (%d шагов, %d с as-if-тегами) -> %s (%d байт) | исходы: %s"
          % (len(rows), tot_steps, tag_steps, out_path, os.path.getsize(out_path), tally),
          flush=True)
    if not tag_steps:
        print("[warn] тегов НЕТ: проверь tactics.enabled_global в points.json и shape_stage.",
              flush=True)


if __name__ == "__main__":
    main()
