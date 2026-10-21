# arent/evaluate.py — долгий горизонт как МЕТРИКА: сколько боёв политика реально выигрывает.
#
# train/bench меряют один ход (val.joint) и скорость. Здесь же политика сети играет ВЕСЬ
# бой в той же Simulation, что размечает учитель (враги отвечают жадно через foes_act), и
# мы считаем накопленную ценность линии, долю выживаний и долю зачисток. Это мост к дуэли
# (Фаза 2): вопрос «стало ли лучше» постепенно переезжает с угадывания одного хода на
# исход боя. Никакого обучения тут нет — только прогон чекпойнта по сценам.
import json
import os
from statistics import mean
from typing import Any, Callable, Dict, List, Optional, Tuple

from arent import backend, encode, paths, play, provenance
from arent import slots as slots_mod
from arent.net import GROUPS, Y_KEY
from arent.observe import observe
from planner.context import BattleContext
from planner.sim import Simulation

Row = Dict[str, Any]


def fight(model: Any, payload: Dict[str, Any], rounds: int = 8) -> Dict[str, Any]:
    """Один бой политикой модели; копит ценность раундов Simulation.advance.

    Раунд: состояние -> наблюдение -> слоты -> предсказание сети -> decode -> advance
    (ход героя + ответ врагов) — ровно та же механика, что в rollout учителя, но вместо
    перебора hero_options() следующий ход выбирает обученная сеть. Стоп: герой погиб,
    врагов не осталось, или уперлись в потолок rounds.
    """
    state = Simulation.of(BattleContext.from_payload(payload))
    total, played = 0.0, 0
    foes_total = len(state.foes)
    while played < max(1, int(rounds)) and not state.hero_dead and state.foes:
        ctx = state.context_for(state.hero_id)
        obs = observe(ctx)
        slots = slots_mod.build(ctx, obs)
        out = model.predict(encode.observation(ctx, obs, slots))
        actions = slots_mod.decode(slots, {Y_KEY[group]: out[Y_KEY[group]] for group in GROUPS})
        state, value = state.advance(actions)
        total += value
        played += 1
    return {"rounds": played, "value": round(total, 3), "survived": not state.hero_dead,
            "cleared": not state.foes, "foes": foes_total, "foes_left": len(state.foes)}


def summarize(rows: List[Dict[str, Any]], model: str = "pure",
              rounds_cap: int = 0) -> Dict[str, Any]:
    """Список боёв -> сводка: средний исход + доли выживания/победы (все доли 0..1)."""
    n = max(1, len(rows))
    return {"fights": len(rows), "model": model, "rounds_cap": rounds_cap,
            "mean_value": round(mean([r["value"] for r in rows]) if rows else 0.0, 3),
            "survival_rate": round(sum(1 for r in rows if r["survived"]) / n, 3),
            "clear_rate": round(sum(1 for r in rows if r["cleared"]) / n, 3),
            "mean_rounds": round(mean([r["rounds"] for r in rows]) if rows else 0.0, 2),
            "rows": rows}


def _sources(arenas: Optional[List[str]], use_live: bool):
    """Сцены для прогона: символьные арены playground + живые снимки (как при генерации)."""
    from arent import dataset
    return list(dataset.sources(arenas, use_live))


def holdout_names(names: List[str], holdout_frac: float, seed: int) -> set:
    """Holdout-множество имён — то же, что режет rl (стабильно по frac/seed, val_frac не влияет)."""
    from arent.splitting import split_source_names
    _train, _val, holdout = split_source_names(names, holdout_frac, 0.0, seed)
    return set(holdout)


def _provenance(model_path: Optional[str], sources: List[Tuple[str, Dict[str, Any]]],
                rounds: int, set_tag: str = "all") -> Dict[str, Any]:
    """Якоря оценки: хеш конкретной модели, тестового набора и конфига — чтобы итог
    нельзя было приписать не той весовой паре. testset = сами payload'ы сцен (не имена).

    set_tag ('independent'/'holdout'/'all') фиксирует, по какому множеству считан итог —
    честное bc2↔PPO-сравнение валидно только при одинаковом set_tag='independent'."""
    names = [str(name) for name, _payload in sources]
    fingerprint = sorted([[str(name), payload] for name, payload in sources], key=lambda r: r[0])
    config = {"rounds": rounds, "sources": sorted(names), "model": model_path}
    return {"model_path": os.path.abspath(model_path) if model_path else None,
            "model_sha256": provenance.sha256_file(model_path) if model_path else None,
            "set_tag": set_tag, "test_sources": sorted(names),
            "testset_sha256": provenance.sha256_obj(fingerprint),
            "eval_config": config, "eval_config_sha256": provenance.sha256_obj(config)}


def run(name: str = "eval", model_path: Optional[str] = None, kind: str = "auto",
        arenas: Optional[List[str]] = None, use_live: bool = True, rounds: int = 8,
        out: Optional[str] = None, holdout_only: bool = False, holdout_frac: float = 0.3,
        split_seed: int = 7, independent: bool = False,
        log: Optional[Callable] = None) -> Dict[str, Any]:
    """Прогнать чекпойнтом по всем сценам (или по выделенному набору); сводка в runs/<имя>/eval.json.

    independent=True — только зарезервированный независимый набор (ho_*): физически
    отделён от обучения bc2 и PPO, значит обе модели идут по одному и тому же честному
    множеству. holdout_only=True оставляет группы случайного split (независимы для PPO,
    но не гарантированно чисты от bc2). independent важнее holdout_only.
    """
    say = log or _echo
    # --model принимает и путь к model.json, и имя прогона (runs/<имя>/model.json) — как в play.
    requested = model_path
    if requested and not os.path.exists(requested):
        requested = play.latest_checkpoint(requested)
        if not requested:
            raise RuntimeError(f"Чекпойнта нет: runs/{model_path}/model.json отсутствует")
    model_path = requested or play.latest_checkpoint()
    if not model_path:
        raise RuntimeError("Чекпойнта нет: сначала arent train (или укажите --model)")
    model = backend.load_policy(model_path, kind=kind)
    if independent:
        from arent import dataset
        sources = dataset.independent_sources(arenas, use_live)
    else:
        sources = _sources(arenas, use_live)
        if holdout_only:
            keep = holdout_names([str(n) for n, _p in sources], holdout_frac, split_seed)
            sources = [(n, p) for n, p in sources if str(n) in keep]
    if not sources:
        raise RuntimeError("Нет сцен: арены playground пусты и живых снимков нет")
    tag = "independent" if independent else ("holdout" if holdout_only else "all")
    say(f"оценка {getattr(model, 'name', 'pure')} [{tag}] на {model_path}: {len(sources)} сцен, "
        f"потолок {rounds} раундов")
    rows: List[Row] = []
    for scene_name, payload in sources:
        row = dict(fight(model, payload, rounds), name=scene_name)
        rows.append(row)
        say(f"{scene_name}: раундов {row['rounds']}, ценность {row['value']}, "
            f"выжил {int(row['survived'])}, зачищено {int(row['cleared'])}")
    report = summarize(rows, model=getattr(model, "name", "pure"), rounds_cap=rounds)
    report["provenance"] = _provenance(model_path, sources, rounds, set_tag=tag)
    _write(paths.file_in(paths.run_dir(name), "eval.json"), report)
    say(f"итог: боёв {report['fights']}, выживаемость {report['survival_rate']}, "
        f"побед {report['clear_rate']}, средняя ценность {report['mean_value']}")
    if out:
        _write(out, report)
    return report


def _write(path: str, data: Any) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))


def _echo(*args: Any) -> None:
    print(*args, flush=True)
