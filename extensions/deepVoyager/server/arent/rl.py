# arent/rl.py — цикл PPO: warm-start, rollout (rollout.py), clipped-обновление, честный eval.
#
# Оптимизируем ИТОГ боя политическим градиентом: актёр — герой (три masked-головы сети),
# враги остаются скриптованными foes_act (зеркальный self-play — Фаза 2). Warm-start берёт
# ствол+action-головы из BC, критик инициализируется заново (см. rl_setup): BC-калибровка
# ценности одного хода не годится как baseline будущих возвратов. Rollout собирается через
# arent.env с потенциальным shaping от замороженного V_ref; best отбирается по ЧЕСТНОМУ
# закрытому циклу на VAL-сценах, HOLDOUT-сцены в обучении/отборе не участвуют вообще.
# Размерности сети и FORMAT model.json не меняются; resume PPO — отдельный ppo_state.pt.
import copy
import os
import random
import time

import torch
from typing import Any, Callable, Dict, List, Optional, Tuple

from arent import backend, dataset, evaluate, manifest, net, paths, provenance, rl_setup, rl_state, spec
from arent.rollout import RlConfig, collect
from arent.torch_rl import PPOAgent

Row = Dict[str, Any]


def _closed_loop(policy: Any, sources: List[Tuple[str, Dict[str, Any]]], rounds: int,
                 replays: int) -> Dict[str, float]:
    """Честная метрика выбора: средний исход боя политикой policy по сценам (N повторов)."""
    rows: List[Row] = []
    for name, payload in sources:
        for _ in range(max(1, replays)):
            rows.append(dict(evaluate.fight(policy, payload, rounds), name=name))
    s = evaluate.summarize(rows, model=getattr(policy, "name", "torch"), rounds_cap=rounds)
    return {"survival": s["survival_rate"], "clear": s["clear_rate"],
            "mean_value": s["mean_value"], "mean_rounds": s["mean_rounds"], "fights": s["fights"]}


def _scoring(summary: Dict[str, float]) -> float:
    """Отбор чекпойнта: выживание затем зачистка. mean_value НЕ в критерии (шкалы несопоставимы)."""
    return summary["survival"] * 1000.0 + summary["clear"] * 100.0


def _split_block(train: List[Row], val: List[Row], holdout: List[Row], rcfg: RlConfig) -> Dict[str, Any]:
    """Фиксируем disjoint-пулы: имена, доли, seed — чтобы holdout нельзя было приписать обучению."""
    return {"method": "grouped-by-name", "seed": rcfg.seed, "holdout_frac": rcfg.holdout_frac,
            "val_frac": rcfg.val_frac, "train_groups": len(train), "val_groups": len(val),
            "holdout_groups": len(holdout), "train": sorted(n for n, _ in train),
            "val": sorted(n for n, _ in val), "holdout": sorted(n for n, _ in holdout),
            "disjoint": bool(not ({n for n, _ in train} & {n for n, _ in holdout})
                             and not ({n for n, _ in val} & {n for n, _ in holdout}))}


def run(name: str = "ppo", warm: Optional[str] = "bc2", rcfg: Optional[RlConfig] = None,
        net_cfg: Optional[net.Config] = None, kind: str = "torch", device: Optional[str] = None,
        arenas: Optional[List[str]] = None, use_live: bool = True, iters: Optional[int] = None,
        rollout: Optional[int] = None, resume: bool = False,
        scenario_sources: Optional[List[Tuple[str, Dict[str, Any]]]] = None,
        log: Optional[Callable] = None) -> Dict[str, Any]:
    """Обучить PPO и сохранить; warm=None — со случайных весов (обычно ставят bc2).

    scenario_sources: явный пул (name, payload) вместо выборки из dataset.sources — так
    пилот гоняет сгенерированные сценарии, НЕ записывая их в боевой каталог арен. Имена
    остаются ключом группировки split (каждая — независимая группа), ho_* сюда не попадают.
    """
    say = log or _echo
    rcfg = rcfg or RlConfig()
    rcfg.iters = iters or rcfg.iters
    rcfg.rollout_steps = rollout or rcfg.rollout_steps
    net_cfg = net_cfg or net.default_config()
    net_cfg.device = device or net_cfg.device
    kind = backend.resolve(kind)
    sources = list(scenario_sources) if scenario_sources is not None \
        else list(dataset.sources(arenas, use_live, exclude_independent=True))
    if not sources:
        raise RuntimeError("Нет сцен: арены playground пусты и живых снимков нет")
    train_pool, val_pool, holdout = rl_setup.split_scenarios(
        sources, rcfg.holdout_frac, rcfg.val_frac, rcfg.seed)
    if not train_pool:
        train_pool, val_pool, holdout = sources, [], []
    select_pool = val_pool or train_pool              # честный отбор на val; val пуст -> in-sample
    if rcfg.variants_per_src > 0:
        train_pool = rl_setup.variant_sources(train_pool, rcfg.seed, rcfg.variants_per_src)
    params, warm_from, vref = (None, None, None)
    if warm:
        params, warm_from = rl_setup.warm_params(net_cfg, warm, rcfg.reset_value_head)
        say(f"warm-start {warm_from} (reset_value_head={rcfg.reset_value_head})")
        if rcfg.use_vref:
            vref, phi = rl_setup.build_vref(net_cfg, warm, net_cfg.device)
        else:
            phi = None
    else:
        phi = None
    policy = backend.build(net_cfg, kind=kind, params=params, device=net_cfg.device)
    agent = PPOAgent(policy, rcfg.clip_eps, rcfg.ent_coef, rcfg.vf_coef, rcfg.ppo_epochs,
                     rcfg.minibatch, rcfg.target_kl)
    for group in policy.optim.param_groups:
        group["lr"] = rcfg.lr
    rng = random.Random(rcfg.seed)
    torch.manual_seed(net_cfg.seed)
    start_iter = _maybe_resume(name, policy, net_cfg, rng, resume, say)
    say(f"PPO {kind} на {getattr(policy, 'device', 'cpu')}: train={len(train_pool)} "
        f"val={len(val_pool)} holdout={len(holdout)} (не обучается на holdout)")
    history: List[Row] = []
    best_score, best_params, best_eval = -1e18, copy.deepcopy(policy.params), None
    started = time.monotonic()
    warm_sha = provenance.sha256_file(warm_from) if warm_from else None
    for it in range(start_iter + 1, rcfg.iters + 1):
        diag: List[Row] = []
        report = agent.update(collect(agent, train_pool, rcfg, rng, phi, diag))
        row: Row = {"iter": it, **report}
        if it % max(1, rcfg.eval_every) == 0 or it == rcfg.iters:
            row["eval"] = _closed_loop(policy, select_pool, rcfg.rounds_cap, rcfg.replays)
            score = _scoring(row["eval"])
            if score > best_score:
                best_score, best_params, best_eval = score, copy.deepcopy(policy.params), row["eval"]
            say(f"iter {it}/{rcfg.iters} loss={report['loss']} kl={report['kl']} "
                f"clip={report['clip_frac']} | survival={row['eval']['survival']} "
                f"clear={row['eval']['clear']}")
        else:
            say(f"iter {it}/{rcfg.iters} loss={report['loss']} kl={report['kl']} "
                f"clip={report['clip_frac']}")
        history.append(row)
        rl_state.save(_state_path(name), policy, rcfg, net_cfg, it, warm_sha, rng.getstate())
        if diag:
            provenance.write_json(paths.file_in(paths.run_dir(name), "shaping_diagnostics.json"),
                                  diag[:64])
    seconds = round(time.monotonic() - started, 2)
    return _finish(name, policy, net_cfg, rcfg, warm_from, history, best_params, best_eval,
                   best_score, seconds, train_pool, _split_block(train_pool, val_pool, holdout, rcfg),
                   vref is not None, say)


def _state_path(name: str) -> str:
    return paths.file_in(paths.run_dir(name), "ppo_state.pt")


def _maybe_resume(name: str, policy: Any, net_cfg: net.Config, rng: random.Random,
                  resume: bool, say: Callable) -> int:
    """Если resume и ppo_state.pt есть: восстановить оптимизатор/итерацию/RNG. Иначе с нуля."""
    if not resume:
        return 0
    path = _state_path(name)
    if not os.path.exists(path):
        say(f"resume запрошен, но {path} нет — начинаем с нуля")
        return 0
    info = rl_state.load(path, policy, net_cfg)
    rl_state.rng_restore(info["rng"] or {})
    scenario = (info["rng"] or {}).get("scenario_rng")
    if scenario is not None:
        rng.setstate(scenario)                    # порядок сцен продолжается побитово (CPU)
    say(f"resume с итерации {info['iteration']}")
    return int(info["iteration"])


def _finish(name: str, policy: Any, net_cfg: net.Config, rcfg: RlConfig, warm_from: Optional[str],
            history: List[Row], best_params: Dict[str, Any], best_eval: Optional[Dict[str, float]],
            best_score: float, seconds: float, scenarios: List[Tuple[str, Dict[str, Any]]],
            split: Dict[str, Any], used_vref: bool, say: Callable) -> Dict[str, Any]:
    """model.json (финал) + model_best.json (лучший закрытый цикл на val) + отчёты + манифест."""
    directory = paths.run_dir(name)
    model_path = net.save(policy, paths.file_in(directory, "model.json"),
                          metrics={"which": "last", "method": "ppo", "iters": len(history),
                                   "backend": policy.name, "closed_loop": history[-1].get("eval")})
    best_path = net.save_params(best_params, net_cfg, policy.name,
                                paths.file_in(directory, "model_best.json"),
                                metrics={"which": "best", "method": "ppo",
                                         "selected_by": "closed_loop_survival_clear_on_val",
                                         "score": round(best_score, 4), "closed_loop": best_eval,
                                         "backend": policy.name})
    summary = {"name": name, "method": "ppo", "iters": len(history), "backend": policy.name,
               "device": str(getattr(policy, "device", "cpu")), "seconds": seconds,
               "scenarios": len(scenarios), "params": net.param_count(net_cfg),
               "warm_from": warm_from, "used_vref": used_vref, "rl": rcfg.to_dict(),
               "network": net_cfg.to_dict(), "best": best_eval, "final": history[-1].get("eval"),
               "best_score": round(best_score, 4), "model": model_path, "model_best": best_path,
               "dims": spec.dims()}
    provenance.write_json(paths.file_in(directory, "history.json"), history)
    provenance.write_json(paths.file_in(directory, "summary.json"), summary)
    manifest.build_and_write_rl(name, net_cfg, rcfg, warm_from, summary, scenarios, split)
    say(f"чекпойнты {model_path} (финал) и {best_path} (лучший val survival/clear) | {seconds} с")
    return {"checkpoint": model_path, "best_checkpoint": best_path, "history": history,
            "summary": summary, "best": best_eval, "final": history[-1].get("eval")}


def _echo(*args: Any) -> None:
    print(*args, flush=True)
