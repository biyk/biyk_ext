# arent/rl.py — цикл PPO: warm-start, rollout (rollout.py), clipped-обновление, честный eval.
#
# Оптимизируем ИТОГ боя политическим градиентом: актёр — герой (три masked-головы сети),
# враги остаются скриптованными foes_act (зеркальный self-play обеих сторон — Фаза 2).
# Стартуем весами из BC (warm-start), собираем траектории средой arent.env (см. rollout.py),
# обновляем PPOAgent, и честно меряем закрытый цикл (evaluate.fight) на тех же сценах —
# метрика выбора чекпойнта это survival/clear боя, а не val.joint одного хода. Размерности
# сети и FORMAT чекпойнта не меняются: PPO-модель читается там, где играет BC.
import copy
import os
import random
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from arent import backend, dataset, evaluate, manifest, net, paths, provenance, spec
from arent.rollout import RlConfig, collect
from arent.torch_rl import PPOAgent

Row = Dict[str, Any]


def _warm_params(net_cfg: net.Config, warm: str) -> Tuple[Dict[str, Any], str]:
    """Весы для warm-start: runs/<имя>/model_best.json (или model.json) либо явный путь."""
    path = warm
    if not (path and os.path.exists(path)):
        base = paths.file_in(paths.run_dir(warm), "model_best.json") if warm else None
        path = base if base and os.path.exists(base) else paths.checkpoint(warm)
    if not path or not os.path.exists(path):
        raise RuntimeError(f"Чекпойнта нет: {warm} — runs/<имя>/model_best.json или путь")
    checkpoint = net.load(path)
    saved = net.Config.from_dict(checkpoint.get("config") or {})
    if (saved.hidden, saved.head) != (net_cfg.hidden, net_cfg.head):
        raise RuntimeError(f"Чекпойнт {path}: hidden={saved.hidden}/head={saved.head}, "
                           f"просим {net_cfg.hidden}/{net_cfg.head}")
    return checkpoint["params"], path


def _closed_loop(policy: Any, sources: List[Tuple[str, Dict[str, Any]]], rounds: int,
                 replays: int) -> Dict[str, float]:
    """Честная метрика выбора: средний исход боя политикой policy по всем сценам (N повторов)."""
    rows: List[Row] = []
    for name, payload in sources:
        for _ in range(max(1, replays)):
            rows.append(dict(evaluate.fight(policy, payload, rounds), name=name))
    s = evaluate.summarize(rows, model=getattr(policy, "name", "torch"), rounds_cap=rounds)
    return {"survival": s["survival_rate"], "clear": s["clear_rate"],
            "mean_value": s["mean_value"], "mean_rounds": s["mean_rounds"], "fights": s["fights"]}


def _scoring(summary: Dict[str, float]) -> float:
    """Порядок отбора чекпойнта: сначала выживание, затем зачистка, затем ценность."""
    return (summary["survival"] * 1000.0 + summary["clear"] * 100.0
            + summary["mean_value"] / spec.VALUE_SCALE)


def run(name: str = "ppo", warm: Optional[str] = "bc2", rcfg: Optional[RlConfig] = None,
        net_cfg: Optional[net.Config] = None, kind: str = "torch", device: Optional[str] = None,
        arenas: Optional[List[str]] = None, use_live: bool = True, iters: Optional[int] = None,
        rollout: Optional[int] = None, log: Optional[Callable] = None) -> Dict[str, Any]:
    """Обучить PPO и сохранить; warm=None — со случайных весов (обычно ставят bc2).

    kind=pure запрещён: RL требует torch-политику (PPOAgent это явно проверяет).
    best отбирается по закрытому циклу (survival/clear), а не по одному ходу.
    """
    say = log or _echo
    rcfg = rcfg or RlConfig()
    rcfg.iters = iters or rcfg.iters
    rcfg.rollout_steps = rollout or rcfg.rollout_steps
    net_cfg = net_cfg or net.default_config()
    net_cfg.device = device or net_cfg.device
    kind = backend.resolve(kind)
    scenarios = list(dataset.sources(arenas, use_live))
    if not scenarios:
        raise RuntimeError("Нет сцен: арены playground пусты и живых снимков нет")
    params, warm_from = (None, None)
    if warm:
        params, warm_from = _warm_params(net_cfg, warm)
        say(f"warm-start от {warm_from} (веса прежние, оптимизатор новый)")
    policy = backend.build(net_cfg, kind=kind, params=params, device=net_cfg.device)
    agent = PPOAgent(policy, rcfg.clip_eps, rcfg.ent_coef, rcfg.vf_coef, rcfg.ppo_epochs,
                     rcfg.minibatch, rcfg.target_kl)
    for group in policy.optim.param_groups:
        group["lr"] = rcfg.lr
    rng = random.Random(rcfg.seed)
    say(f"PPO {kind} на {getattr(policy, 'device', 'cpu')}: {len(scenarios)} сцен, "
        f"{rcfg.iters} итераций по {rcfg.rollout_steps} шагов")
    history: List[Row] = []
    best_score, best_params, best_eval = -1e18, copy.deepcopy(policy.params), None
    started = time.monotonic()
    for it in range(1, rcfg.iters + 1):
        report = agent.update(collect(agent, scenarios, rcfg, rng))
        row: Row = {"iter": it, **report}
        if it % max(1, rcfg.eval_every) == 0 or it == rcfg.iters:
            row["eval"] = _closed_loop(policy, scenarios, rcfg.rounds_cap, rcfg.replays)
            score = _scoring(row["eval"])
            if score > best_score:
                best_score, best_params, best_eval = score, copy.deepcopy(policy.params), row["eval"]
            say(f"iter {it}/{rcfg.iters} loss={report['loss']} kl={report['kl']} "
                f"clip={report['clip_frac']} ent={report['entropy']} | "
                f"survival={row['eval']['survival']} clear={row['eval']['clear']}")
        else:
            say(f"iter {it}/{rcfg.iters} loss={report['loss']} kl={report['kl']} "
                f"clip={report['clip_frac']} ent={report['entropy']}")
        history.append(row)
    seconds = round(time.monotonic() - started, 2)
    return _finish(name, policy, net_cfg, rcfg, warm_from, history, best_params, best_eval,
                   best_score, seconds, scenarios, say)


def _finish(name: str, policy: Any, net_cfg: net.Config, rcfg: RlConfig, warm_from: Optional[str],
            history: List[Row], best_params: Dict[str, Any], best_eval: Optional[Dict[str, float]],
            best_score: float, seconds: float, scenarios: List[Tuple[str, Dict[str, Any]]],
            say: Callable) -> Dict[str, Any]:
    """Записать model.json (финальные веса) + model_best.json (лучший закрытый цикл) и отчёты."""
    directory = paths.run_dir(name)
    model_path = net.save(policy, paths.file_in(directory, "model.json"),
                          metrics={"which": "last", "method": "ppo", "iters": len(history),
                                   "backend": policy.name, "closed_loop": history[-1].get("eval")})
    best_path = net.save_params(best_params, net_cfg, policy.name,
                                paths.file_in(directory, "model_best.json"),
                                metrics={"which": "best", "method": "ppo",
                                         "selected_by": "closed_loop_survival",
                                         "score": round(best_score, 4), "closed_loop": best_eval,
                                         "backend": policy.name})
    summary = {"name": name, "method": "ppo", "iters": len(history), "backend": policy.name,
               "device": str(getattr(policy, "device", "cpu")), "seconds": seconds,
               "scenarios": len(scenarios), "params": net.param_count(net_cfg),
               "warm_from": warm_from, "rl": rcfg.to_dict(), "network": net_cfg.to_dict(),
               "best": best_eval, "final": history[-1].get("eval"),
               "best_score": round(best_score, 4), "model": model_path, "model_best": best_path,
               "dims": spec.dims()}
    provenance.write_json(paths.file_in(directory, "history.json"), history)
    provenance.write_json(paths.file_in(directory, "summary.json"), summary)
    manifest.build_and_write_rl(name, net_cfg, rcfg, warm_from, summary, scenarios)
    say(f"чекпойнты {model_path} (финал) и {best_path} (лучший survival/clear) | {seconds} с")
    return {"checkpoint": model_path, "best_checkpoint": best_path, "history": history,
            "summary": summary, "best": best_eval, "final": history[-1].get("eval")}


def _echo(*args: Any) -> None:
    print(*args, flush=True)
