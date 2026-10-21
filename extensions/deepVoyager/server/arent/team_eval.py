# arent/team_eval.py — приёмочная метрика «универсального солдата»: win-rate КОМАНДЫ.
#
# evaluate.fight мерит старый моноакторный контур (герой + скриптовые foes_act, итог
# «выжил/зачистил»). Здесь — новый контур: каждый живой юнит обеих сторон ходит ОДНОЙ
# политикой через PolyFightEnv (self-play, WP3), итог боя — исход команды по TeamReward
# (win/loss/draw/mutual, WP4), эпизоды стартуют с разных актёров (start_index, WP5).
# Прогон детерминирован (среда считает ожиданием, predict — argmax), поэтому до/после
# сравнение на замороженном независимом наборе ho_/ho2_ честно для одних и тех же весов.
import os
from statistics import mean
from typing import Any, Callable, Dict, List, Optional, Tuple

from arent import backend, dataset, evaluate, paths, play, polyenv
from arent.team_reward import TeamReward

Row = Dict[str, Any]


def team_fight(model: Any, payload: Dict[str, Any], rounds_cap: int = 8,
               draw_window: int = 4, start_index: int = 0) -> Row:
    """Один бой: вся сцена ходит политикой модели, терминал — исход команды."""
    environment = polyenv.PolyFightEnv(rounds_cap=rounds_cap,
                                       team=TeamReward(draw_window=draw_window))
    obs = environment.reset(payload, start_index=start_index)
    start_actor = environment.actor
    steps, total, outcome, info = 0, 0.0, "open", {}
    while obs is not None:
        out = model.predict(obs)
        label = {k: int(out.get(k, -1)) for k in ("cell", "target", "weapon")}
        obs, reward, terminated, truncated, info = environment.step(label)
        steps += 1
        total += reward
        if terminated:
            outcome = info["outcome"]
            break
        if truncated:
            break                                       # усечение cap'ом: бой не решён
    alive = lambda hostile: sum(1 for u in environment.state.units.values()
                                if u.is_alive and u.hostile_to_hero == hostile)
    return {"outcome": outcome, "terminated": bool(info.get("terminated", False)),
            "rounds": int(info.get("rounds", 0)), "steps": steps,
            "reward": round(total, 4), "ours_alive": alive(False), "foes_alive": alive(True),
            "start_actor": start_actor}


def evaluate_sources(model: Any, sources: List[Tuple[str, Dict[str, Any]]],
                     rounds_cap: int = 8, draw_window: int = 4,
                     replays: int = 1) -> List[Row]:
    """Все сцены x replays повторов; повтор k стартует с k-го актёра (ротация WP5)."""
    rows: List[Row] = []
    for name, payload in sources:
        for rep in range(max(1, replays)):
            rows.append(dict(team_fight(model, payload, rounds_cap, draw_window,
                                        start_index=rep), name=name))
    return rows


def summarize_team(rows: List[Row], model: str = "pure", rounds_cap: int = 0) -> Row:
    """Доли исходов команды (0..1) + средняя длительность; «open» — дожившие до cap."""
    n = max(1, len(rows))
    rate = lambda outcome: round(sum(1 for r in rows if r["outcome"] == outcome) / n, 4)
    return {"fights": len(rows), "model": model, "rounds_cap": rounds_cap,
            "win_rate": rate("win"), "loss_rate": rate("loss"), "draw_rate": rate("draw"),
            "mutual_rate": rate("mutual"), "open_rate": rate("open"),
            "mean_rounds": round(mean([r.get("rounds", 0) for r in rows]) if rows else 0.0, 2),
            "mean_reward": round(mean([r.get("reward", 0.0) for r in rows]) if rows else 0.0, 3),
            "rows": rows}


def run(name: str = "team_eval", model_path: Optional[str] = None, kind: str = "auto",
        arenas: Optional[List[str]] = None, use_live: bool = True, rounds_cap: int = 8,
        draw_window: int = 4, replays: int = 1, independent: bool = True,
        out: Optional[str] = None, log: Optional[Callable] = None) -> Row:
    """Прогнировать чекпойнтом командным контуром; сводка в runs/<имя>/team_eval.json.

    independent=True — только ho_/ho2_ (физически отделён от train/reward bc2 и PPO):
    именно так сравниваются «до» (моноакторный evaluate.run) и «после» (этот прогон)
    на одних весах и одном честном множестве с якорями provenance.
    """
    say = log or _echo
    requested = model_path
    if requested and not os.path.exists(requested):
        requested = play.latest_checkpoint(requested)
        if not requested:
            raise RuntimeError(f"Чекпойнта нет: runs/{model_path}/model.json отсутствует")
    model_path = requested or play.latest_checkpoint()
    if not model_path:
        raise RuntimeError("Чекпойнта нет: сначала arent train/rl (или укажите --model)")
    model = backend.load_policy(model_path, kind=kind)
    if independent:
        sources = dataset.independent_sources(arenas, use_live)
    else:
        sources = list(dataset.sources(arenas, use_live, exclude_independent=True))
    if not sources:
        raise RuntimeError("Нет сцен: арены playground пусты и живых снимков нет")
    tag = "independent" if independent else "non-independent"
    say(f"командная оценка {getattr(model, 'name', 'pure')} [{tag}] на {model_path}: "
        f"{len(sources)} сцен x{replays}, cap {rounds_cap} раундов")
    rows = evaluate_sources(model, sources, rounds_cap, draw_window, replays)
    report = summarize_team(rows, model=getattr(model, "name", "pure"), rounds_cap=rounds_cap)
    report["provenance"] = evaluate._provenance(model_path, sources, rounds_cap, set_tag=tag)
    for row in rows:
        say(f"{row['name']}: исход {row['outcome']}, раундов {row['rounds']}, "
            f"наш живых {row['ours_alive']}, врагов {row['foes_alive']}")
    evaluate._write(paths.file_in(paths.run_dir(name), "team_eval.json"), report)
    say(f"итог: win {report['win_rate']}, loss {report['loss_rate']}, "
        f"draw {report['draw_rate']}, mutual {report['mutual_rate']}, "
        f"open {report['open_rate']}")
    if out:
        evaluate._write(out, report)
    return report


def _echo(*args: Any) -> None:
    print(*args, flush=True)
