# arent/manifest.py — run_manifest.json: чем именно и на чём выучен этот чекпойнт.
#
# summary.json отвечает «что получилось», но не «из чего»: тот же файл можно получить с
# другого датасета, кода и seed. Манифест рядом с прогоном связывает веса с источником:
# команду, UTC, git (commit/dirty/отпечаток кода), SHA-256 датасета и выхода, параметры
# генерации отдельно от seed обучения, родителя --warm и разбивку разделения. Неизвестное
# пишется как unknown/None — старые прогоны не додумываем.
import os
import sys
from typing import Any, Dict, Optional

from arent import backend, net, paths, provenance, spec

OUTPUTS = ("model.json", "model_best.json", "summary.json", "history.json")
RL_OUTPUTS = OUTPUTS + ("eval.json",)


def _gen_block(sidecar: Dict[str, Any]) -> Dict[str, Any]:
    """Параметры генерации из сайдкара; то, чего нет, — честно unknown, не выдумка."""
    keys = ("seed", "count", "per_src", "teacher_rounds", "shallow_k", "top_k", "rounds_max")
    block = {k: sidecar.get(k, "unknown") for k in keys}
    block["source"] = "dataset.meta.json" if sidecar else "unknown (сайдкар не сохранён)"
    block["schema"] = sidecar.get("schema", "unknown")
    return block


def build(name: str, cfg: net.Config, dataset_file: Optional[str], split_report: Optional[Dict],
          val_source: str, warm_from: Optional[str], summary: Dict[str, Any]) -> Dict[str, Any]:
    directory = paths.run_dir(name)
    sidecar = provenance.read_sidecar(dataset_file) if dataset_file else {}
    dataset_block = {
        "name": os.path.splitext(os.path.basename(dataset_file))[0] if dataset_file else None,
        "path": os.path.abspath(dataset_file) if dataset_file else None,
        "bytes": os.path.getsize(dataset_file) if dataset_file and os.path.exists(dataset_file) else None,
        "sha256": provenance.sha256_file(dataset_file) if dataset_file else None,
        "samples": summary.get("samples"),
        "available": bool(dataset_file and os.path.exists(dataset_file or "")),
    }
    outputs = {name_: provenance.sha256_file(paths.file_in(directory, name_)) for name_ in OUTPUTS}
    warm = None
    if warm_from:
        warm = {"parent_path": os.path.abspath(warm_from),
                "parent_sha256": provenance.sha256_file(warm_from)}
    return {
        "manifest_schema": 1,
        "schema": spec.SCHEMA,
        "compatibility": {"from_schema": None, "reason": "v2 team combat, no warm-start",
                          "breaks": ["single_actor_sc1_benchmarks"]},
        "run": name,
        "created_utc": provenance.now_utc(),
        "command": list(sys.argv),
        "workspace": paths.workspace(),
        "git": provenance.git_info(paths.source_dir()),
        "dataset": dataset_block,
        "generation": _gen_block(sidecar),
        "training": {"seed": cfg.seed, "epochs": summary.get("epochs"), "batch": cfg.batch,
                     "lr": cfg.lr, "hidden": cfg.hidden, "head": cfg.head, "value_w": cfg.value_w,
                     "weight_decay": cfg.weight_decay, "momentum": cfg.momentum,
                     "val_frac": cfg.val_frac, "kind": cfg.kind, "device": summary.get("device"),
                     "best_metric": summary.get("best_metric"), "val_source": val_source},
        "network": {"config": cfg.to_dict(), "dims": net.dims_for(cfg.schema),
                    "feature_version": net.feature_version(cfg.schema),
                    "params": net.param_count(cfg), "backend": summary.get("backend")},
        "environment": backend.describe(),
        "split": split_report if split_report else {"method": val_source},
        "warm": warm,
        "outputs": {"paths": {n: paths.file_in(directory, n) for n in OUTPUTS}, "sha256": outputs},
    }


def build_and_write(name: str, cfg: net.Config, dataset_file: Optional[str],
                    split_report: Optional[Dict], val_source: str, warm_from: Optional[str],
                    summary: Dict[str, Any]) -> str:
    manifest = build(name, cfg, dataset_file, split_report, val_source, warm_from, summary)
    return provenance.write_json(paths.file_in(paths.run_dir(name), "run_manifest.json"), manifest)


def build_rl(name: str, net_cfg: net.Config, rcfg: Any, warm_from: Optional[str],
             summary: Dict[str, Any], scenarios: Optional[list] = None,
             split: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """RL-прогон: method=ppo, родитель warm (BC), отпечаток сцен обучения, seeds раздельно.

    train_seed (инициализация сети/мультиномиальный sampling torch) и env_seed (порядок сцен
    в rollout) пишутся отдельными ключами — их нельзя путать. eval.json может отсутствовать
    (его делает отдельный шаг evaluate) — тогда sha честно None, не выдумываем.
    split фиксирует, что holdout-сцены не участвовали ни в rollout, ни в отборе чекпойнта.
    """
    directory = paths.run_dir(name)
    scenarios = scenarios or []
    names = sorted(str(n) for n, _p in scenarios)
    fingerprint = sorted([[str(n), p] for n, p in scenarios], key=lambda r: r[0])
    warm = {"parent_path": os.path.abspath(warm_from),
            "parent_sha256": provenance.sha256_file(warm_from)} if warm_from else None
    outputs = {f: provenance.sha256_file(paths.file_in(directory, f)) for f in RL_OUTPUTS}
    return {
        "manifest_schema": 1, "schema": spec.SCHEMA, "run": name, "method": "ppo",
        "compatibility": {"from_schema": None, "reason": "v2 team combat, no warm-start",
                          "breaks": ["single_actor_sc1_benchmarks"]},
        "created_utc": provenance.now_utc(),
        "command": list(sys.argv), "workspace": paths.workspace(),
        "git": provenance.git_info(paths.source_dir()),
        "training_scenarios": {"count": len(scenarios), "sources": names,
                               "sha256": provenance.sha256_obj(fingerprint) if scenarios else None},
        "split": split or {"method": "unknown"},
        "warm": warm,
        "seeds": {"train_seed": net_cfg.seed, "env_seed": getattr(rcfg, "seed", None)},
        "rl": rcfg.to_dict() if hasattr(rcfg, "to_dict") else dict(rcfg or {}),
        "network": {"config": net_cfg.to_dict(), "dims": net.dims_for(net_cfg.schema),
                    "feature_version": net.feature_version(net_cfg.schema),
                    "params": net.param_count(net_cfg), "backend": summary.get("backend")},
        "environment": backend.describe(),
        "closed_loop": {"best": summary.get("best"), "final": summary.get("final"),
                        "best_score": summary.get("best_score")},
        "outputs": {"paths": {f: paths.file_in(directory, f) for f in RL_OUTPUTS},
                    "sha256": outputs},
    }


def build_and_write_rl(name: str, net_cfg: net.Config, rcfg: Any, warm_from: Optional[str],
                       summary: Dict[str, Any], scenarios: Optional[list] = None,
                       split: Optional[Dict[str, Any]] = None) -> str:
    manifest = build_rl(name, net_cfg, rcfg, warm_from, scenarios=scenarios, split=split,
                        summary=summary)
    return provenance.write_json(paths.file_in(paths.run_dir(name), "run_manifest.json"), manifest)
