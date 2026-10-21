# playground/run.py — прогон арен через настоящий планировщик (пункт 5).
#
# Матрица «арена × глубина × таймер»: для каждой ячейки замеряем латентность хода,
# достигнутую глубину и — главное — значение выбранной линии, посчитанное НЕ оценкой
# планировщика, а независимой симуляцией на фиксированное число раундов. Только так
# greedy (rounds=1) и lookahead сравнимы в одной шкале.
import argparse
import dataclasses
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from planner.action import ACTION_MOVE, Action
from planner.context import BattleContext
from planner.points import default_tuning, set_tuning
from planner.service import PlannerService
from planner.turns import rollout
from playground.arena import ARENA_NAMES, load_arena

#: колонки таблицы: (заголовок, ширина, ключ Row)
COLUMNS = (("арена", 16, "arena"), ("гл", 4, "rounds"), ("тайм", 6, "timer"),
           ("латент", 7, "latency"), ("глуб", 5, "depth"), ("узлы", 6, "nodes"),
           ("значение", 9, "value"), ("вариантов", 9, "considered"))


@dataclass(frozen=True)
class Row:
    """Одна ячейка матрицы: что считали, сколько заняли и чем это кончилось."""
    arena: str
    rounds: int               # lookahead.rounds в этой ячейке
    timer: float              # limits.planTimeLimitSec
    latency: float            # сколько секунд планирование действительно заняло
    depth: int                # до какой глубины успели
    nodes: int
    value: float              # значение линии в общей шкале (rollout)
    plan: str                 # выбранные действия человекочитаемо
    metric_rounds: int        # сколько раундов насчитала метрика (одинаково для всех)
    considered: int = 0
    report: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


def format_plan(actions: Sequence[Action]) -> str:
    """«target E1 · move left×2 · use sword» — план в одну строку таблицы."""
    groups: List[List[Any]] = []
    for a in actions:
        if a.action == ACTION_MOVE:
            label, key = "move", a.conf.get("direction")
        else:
            label, key = a.action, a.conf.get("id") or a.conf.get("itemId") or ""
        if groups and groups[-1][:2] == [label, key]:
            groups[-1][2] += 1
        else:
            groups.append([label, key, 1])
    return " · ".join(f"{label} {key}".rstrip() + (f"×{n}" if n > 1 else "")
                      for label, key, n in groups)


def _tuning(depth: int, timer: float, extra: Dict[str, Any]):
    return dataclasses.replace(default_tuning(), max_rounds=depth,
                               plan_time_limit_sec=timer, **extra)


def run_one(name: str, payload: Dict[str, Any], depth: int, timer: float,
            metric_rounds: int, **extra) -> Row:
    """Один прогон: пины настроек -> замер -> метрика -> восстановление настроек."""
    context = BattleContext.from_payload(payload)
    previous = set_tuning(_tuning(depth, timer, extra))
    try:
        started = time.perf_counter()
        result = PlannerService().plan_result(context)
        latency = time.perf_counter() - started
        value = rollout(context, result.actions, metric_rounds)
    finally:
        set_tuning(previous)
    return Row(arena=name, rounds=depth, timer=timer, latency=round(latency, 3),
               depth=result.depth, nodes=result.nodes, value=float(value),
               plan=format_plan(result.actions), metric_rounds=metric_rounds,
               considered=result.considered, report=result.report)


def run_matrix(names: Optional[Iterable[str]] = None, depths: Iterable[int] = (1, 2, 3),
               timers: Iterable[float] = (2.0, 3.0, 5.0),
               metric_rounds: Optional[int] = None, **extra) -> List[Row]:
    """Строки матрицы в порядке арена -> глубина -> таймер (метрика — общая)."""
    chosen = list(names) if names else list(ARENA_NAMES)
    unknown = [n for n in chosen if n not in ARENA_NAMES]
    if unknown:
        raise ValueError(f"неизвестная арена: {', '.join(unknown)}")
    depth_list = [int(d) for d in depths]
    timer_list = [float(x) for x in timers]
    rounds = max(depth_list) if metric_rounds is None else int(metric_rounds)
    rows: List[Row] = []
    for name in chosen:
        payload = load_arena(name)
        for depth in depth_list:
            for timer in timer_list:
                rows.append(run_one(name, payload, depth, timer, rounds, **extra))
    return rows


def format_table(rows: Sequence[Row]) -> str:
    """Текстовая таблица для консоли (значения — в общей шкале rollout)."""
    head = " ".join(f"{title:>{width}}" for title, width, _key in COLUMNS) + "  план"
    lines = [head]
    for row in rows:
        cells = []
        for _title, width, key in COLUMNS:
            value = getattr(row, key)
            cells.append(f"{value:>{width}.1f}" if isinstance(value, float)
                         else f"{value!s:>{width}}")
        lines.append(" ".join(cells) + f"  {row.plan}")
    return "\n".join(lines)


def _numbers(text: str) -> List[float]:
    return [float(part) for part in text.replace(" ", "").split(",") if part]


def main(argv: Optional[List[str]] = None) -> int:
    """CLI площадки: python -m playground --rounds 1,2,3 --timers 2,3,5."""
    parser = argparse.ArgumentParser(prog="playground", description=__doc__)
    parser.add_argument("--arena", default="", help="арены через запятую; пусто — все")
    parser.add_argument("--rounds", default="1,2,3", help="значения lookahead.rounds")
    parser.add_argument("--timers", default="2,3,5", help="значения limits.planTimeLimitSec")
    parser.add_argument("--metric", type=int, default=None, help="раундов для общей метрики")
    parser.add_argument("--json", dest="json_path", default=None, help="сюда пишет строки")
    args = parser.parse_args(argv)
    names = [part for part in args.arena.replace(" ", "").split(",") if part]
    unknown = [n for n in names if n not in ARENA_NAMES]
    if unknown:
        print(f"неизвестная арена: {', '.join(unknown)}\nдоступны: {', '.join(ARENA_NAMES)}")
        return 2
    rows = run_matrix(names or None, [int(x) for x in _numbers(args.rounds)],
                      _numbers(args.timers), args.metric)
    print(format_table(rows))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in rows], f, ensure_ascii=False, indent=2)
        print(f"записано: {args.json_path}")
    return 0
