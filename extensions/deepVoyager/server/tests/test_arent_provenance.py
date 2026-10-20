# tests/test_arent_provenance.py — манифест прогона, хеши и необрываемое происхождение.
#
# Проверяем якоря воспроизводимости, а не красивые числа: run_manifest.json обязан
# содержать команду, UTC, git, SHA-256 датасета и выходов, отделить seed генерации от
# seed обучения и записать родителя --warm; append — не терять параметры генерации.
import hashlib
import json
import os

from arent import dataset, evaluate, manifest, net, paths, provenance, spec, train
from arent.splitting import UnsafeSplit
import pytest


def _row(arena, variant):
    d = spec.dims()
    base = (sum(ord(c) for c in arena) + variant) / 100.0
    return {"schema": spec.SCHEMA, "state": [base] * d["state"],
            "cells": [[base] * d["cell_feat"] for _ in range(d["cells"])],
            "targets": [[base] * d["target_feat"] for _ in range(d["targets"])],
            "weapons": [[base] * d["weapon_feat"] for _ in range(d["weapons"])],
            "mask": {"cells": [1] * d["cells"], "targets": [1] * d["targets"],
                     "weapons": [1] * d["weapons"]},
            "y": {"cell": 0, "target": 0, "weapon": 0}, "value": 0.1,
            "meta": {"arena": arena, "src": "A", "variant": variant}}


def _pool():
    return [_row(a, v) for a in ("alpha", "beta", "gamma") for v in range(3)]


def _gen_stats():
    return {"schema": spec.SCHEMA, "seed": 7, "teacher_rounds": 2, "shallow_k": 3,
            "top_k": 4, "count": 600, "per_src": 6, "rounds_max": 3, "skip": {},
            "sources": {"alpha": 3}}


def test_run_manifest_captures_provenance(tmp_path):
    paths.set_workspace(str(tmp_path))
    dataset.save(_pool(), "dset", stats=_gen_stats())
    cfg = net.Config(hidden=8, head=2, seed=5, epochs=1, batch=4)
    train_run(cfg, "dset", "m")
    manifest = _manifest("m")
    assert manifest["command"] and isinstance(manifest["command"], list)
    assert manifest["created_utc"].endswith("+00:00")
    assert set({"commit", "branch", "dirty", "code_sha256"}) <= set(manifest["git"])
    ds = manifest["dataset"]
    assert ds["sha256"] == provenance.sha256_file(ds["path"]) and ds["samples"] == 9
    assert manifest["generation"]["teacher_rounds"] == 2 and manifest["generation"]["seed"] == 7
    assert manifest["training"]["seed"] == 5 and manifest["training"]["seed"] != manifest["generation"]["seed"]
    assert manifest["outputs"]["sha256"]["model.json"] == provenance.sha256_file(
        manifest["outputs"]["paths"]["model.json"])
    assert manifest["split"]["method"] == "grouped" and manifest["split"]["group_overlap"] == []
    assert manifest["warm"] is None


def test_run_manifest_records_warm_parent(tmp_path):
    paths.set_workspace(str(tmp_path))
    dataset.save(_pool(), "dset", stats=_gen_stats())
    cfg = net.Config(hidden=8, head=2, seed=5, epochs=1, batch=4)
    train_run(cfg, "dset", "parent")
    train_run(cfg, "dset", "child", warm="parent")
    manifest = _manifest("child")
    parent = manifest["warm"]["parent_path"]
    assert parent.endswith(os.path.join("parent", "model.json"))
    assert manifest["warm"]["parent_sha256"] == provenance.sha256_file(parent)


def test_manifest_unknown_when_dataset_is_in_memory(tmp_path):
    """Синтетика без файла: происхождение датасета пишется unknown/None, а не выдумывается."""
    paths.set_workspace(str(tmp_path))
    cfg = net.Config(hidden=8, head=2, seed=5, epochs=1, batch=4)
    train.run(name="mem", samples=_pool(), cfg=cfg, kind="pure", epochs=1, batch=4,
              log=lambda *_a: None)
    manifest = _manifest("mem")
    assert manifest["dataset"]["sha256"] is None
    assert manifest["generation"]["source"].startswith("unknown")


def test_append_does_not_lose_generation_provenance(tmp_path):
    paths.set_workspace(str(tmp_path))
    dataset.save(_pool()[:3], "acc", stats=_gen_stats())
    stats2 = _gen_stats()
    stats2["sources"] = {"beta": 2}
    dataset.append(_pool()[3:5], "acc", stats=stats2)
    sidecar = provenance.read_sidecar(dataset.samples_file("acc"))
    assert sidecar["sources"] == {"alpha": 3, "beta": 2}     # источники сложились
    assert sidecar["samples"] == 5 and sidecar["teacher_rounds"] == 2
    assert len(sidecar["gen_log"]) == 1                       # журнал append-операции


def test_eval_provenance_hashes_model_and_testset(tmp_path):
    model_file = tmp_path / "model.json"
    model_file.write_bytes(b"weight-bytes")
    sources = [("beta", {"x": 1}), ("alpha", {"y": 2})]
    prov = evaluate._provenance(str(model_file), sources, rounds=8)
    assert prov["model_sha256"] == hashlib.sha256(b"weight-bytes").hexdigest()
    assert prov["test_sources"] == ["alpha", "beta"]
    assert len(prov["testset_sha256"]) == 64 and len(prov["eval_config_sha256"]) == 64
    other = evaluate._provenance(str(model_file), [("beta", {"x": 9}), ("alpha", {"y": 2})], 8)
    assert other["testset_sha256"] != prov["testset_sha256"]   # состояние сцены меняет отпечаток


def test_sha256_obj_is_stable_and_git_never_raises():
    assert provenance.sha256_obj({"a": 1, "b": 2}) == provenance.sha256_obj({"b": 2, "a": 1})
    info = provenance.git_info(paths.source_dir())
    assert {"commit", "dirty", "code_sha256", "error"} <= set(info)
    assert len(provenance.code_fingerprint(paths.source_dir())) == 64   # отпечаток кода есть
    assert provenance.sha256_file(os.path.join(paths.source_dir(), "nonexistent")) is None


def train_run(cfg, dataset_name, name, warm=None):
    return train.run(name=name, dataset_name=dataset_name, cfg=cfg, kind="pure",
                     epochs=cfg.epochs, batch=cfg.batch, warm=warm, log=lambda *_a: None)


def _manifest(name):
    path = paths.file_in(paths.run_dir(name), "run_manifest.json")
    assert os.path.exists(path), "run_manifest.json не записан"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_grouped_split_is_used_by_train(tmp_path):
    """train.run обязан разделять по сценариям: утечка групп в summary запрещена."""
    paths.set_workspace(str(tmp_path))
    dataset.save(_pool(), "dset", stats=_gen_stats())
    cfg = net.Config(hidden=8, head=2, seed=5, epochs=1, batch=4)
    report = train_run(cfg, "dset", "gr")
    split = report["summary"]["split"]
    assert split["method"] == "grouped" and split["group_overlap"] == []
    assert split["train_groups"] + split["val_groups"] == split["groups_total"]


def test_train_refuses_dataset_without_two_scenarios(tmp_path):
    paths.set_workspace(str(tmp_path))
    dataset.save([_row("solo", v) for v in range(4)], "one", stats=_gen_stats())
    cfg = net.Config(hidden=8, head=2, seed=5, epochs=1, batch=4)
    with pytest.raises(UnsafeSplit):
        train_run(cfg, "one", "bad")


def test_rl_manifest_records_ppo_provenance(tmp_path):
    """RL-прогон: method=ppo, sha родителя warm, env_seed != train_seed, отпечаток сцен."""
    paths.set_workspace(str(tmp_path))

    class _R:
        seed = 9
        def to_dict(self):
            return {"seed": 9, "iters": 2, "gamma": 0.98}

    warm = paths.file_in(paths.run_dir("bcp"), "model_best.json")
    with open(warm, "w", encoding="utf-8") as f:
        f.write("weights")
    net_cfg = net.Config(hidden=8, head=2, seed=5)
    summary = {"backend": "torch", "best": {"survival": 0.5},
               "final": {"survival": 0.5}, "best_score": 1.0}
    m = manifest.build_rl("pporun", net_cfg, _R(), warm, summary,
                          scenarios=[("arenaB", {"x": 1}), ("arenaA", {"y": 2})])
    assert m["method"] == "ppo"
    assert m["warm"]["parent_sha256"] == provenance.sha256_file(warm)
    assert m["seeds"] == {"train_seed": 5, "env_seed": 9}
    assert m["training_scenarios"]["sources"] == ["arenaA", "arenaB"]
    assert len(m["training_scenarios"]["sha256"]) == 64
    assert m["outputs"]["sha256"]["eval.json"] is None      # eval.json ещё не сделан — честно None
