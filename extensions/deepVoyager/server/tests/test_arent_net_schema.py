# tests/test_arent_net_schema.py — F-B.2b: net-профиль по схеме + отказ несовместимых весов.
#
# Значение по умолчанию во всём профиле = схема 2, поэтому прежние вызовы (и весь v2-путь)
# работают бит-в-бит. Схема 3 меняет только голову клеток: ширину признаков (CELL3_FEATURES),
# число слотов (K_MOVEPLAN+1) и ключ метки (plan вместо cell). Проверяем профиль, инициализацию,
# обучение/предсказание pure-политика на schema-3 выборке, save/load и то, что v2-веса в v3
# сеть (и наоборот) ОТКАЗЫВАЮТСЯ с явной ошибкой.
import pytest

from arent import backend, net, rl_setup, spec, spec3


def _v3_sample():
    d = spec3.dims3()
    return {
        "schema": 3, "state": [0.1] * d["state"],
        "cells": [[0.1] * d["cell_feat"] for _ in range(d["cells"])],
        "targets": [[0.1] * d["target_feat"] for _ in range(d["targets"])],
        "weapons": [[0.1] * d["weapon_feat"] for _ in range(d["weapons"])],
        "mask": {"cells": [1] * d["cells"], "targets": [1] * d["targets"],
                 "weapons": [1] * d["weapons"]},
        "y": {"plan": 0, "target": 0, "weapon": 0},
        "value": 0.3, "meta": {"arena": "gen_x"},
    }


def test_profile_defaults_to_schema2_parity():
    # схема 2 = прежнее поведение: dims/slot_size/y_key без аргумента совпадают с v2-константами
    assert net.dims_for(2) == spec.dims() and net.dims_for() == spec.dims()
    assert net.slot_size("cells") == len(spec.CELL_FEATURES)
    assert net.slot_size("cells", 2) == len(spec.CELL_FEATURES)
    assert net.y_key(2) == net.Y_KEY
    # схема 3 отличается ТОЛЬКО головой клеток
    assert net.dims_for(3) == spec3.dims3()
    assert net.slot_size("cells", 3) == len(spec3.CELL3_FEATURES) != len(spec.CELL_FEATURES)
    assert net.slot_size("targets", 3) == len(spec.ENEMY_FEATURES)      # цели/оружие общие
    assert net.y_key(3)["cells"] == "plan" and net.y_key(3)["targets"] == "target"


def test_init_params_and_param_count_track_schema():
    cfg3 = net.Config(schema=3, hidden=8, head=6)
    p3 = net.init_params(cfg3)
    assert len(p3["headW"]["cells"][0]) == cfg3.head + len(spec3.CELL3_FEATURES)
    assert len(p3["headW"]["targets"][0]) == cfg3.head + len(spec.ENEMY_FEATURES)
    assert net.param_count(cfg3) == net.param_count(cfg3, spec3.dims3())
    cfg2 = net.Config(hidden=8, head=6)
    assert net.slot_size("cells", cfg2.schema) == len(spec.CELL_FEATURES)


def test_pure_policy_trains_and_saves_schema3(tmp_path):
    cfg = net.Config(schema=3, hidden=8, head=6, epochs=1)
    model = backend.build(cfg, kind="pure")
    sample = _v3_sample()
    report = model.step_batch([sample], lr=0.1)
    assert "plan" in report                                    # отчёт головы клеток — по ключу схемы 3
    out = model.predict(sample)
    assert "plan" in out and "cell" not in out
    assert net.y_index(sample, "cells", 3) == 0
    path = net.save(model, str(tmp_path / "m3.json"), metrics={"n": 1})
    ckpt = net.load(path, expect_schema=3)
    assert ckpt["schema"] == 3 and ckpt["dims"] == spec3.dims3()
    assert ckpt["config"]["schema"] == 3
    # reload -> тот же предсказательный контракт
    again = backend.load_policy(path, kind="pure")
    assert "plan" in again.predict(sample)


def test_cross_schema_weights_are_rejected(tmp_path):
    v2 = backend.build(net.Config(schema=2, hidden=8, head=6), kind="pure")
    v3 = backend.build(net.Config(schema=3, hidden=8, head=6), kind="pure")
    p2 = net.save(v2, str(tmp_path / "m2.json"))
    p3 = net.save(v3, str(tmp_path / "m3.json"))
    # load с нужной схемой ок, с чужой — ValueError
    assert net.load(p3, expect_schema=3)["schema"] == 3
    with pytest.raises(ValueError, match="SCHEMA"):
        net.load(p3, expect_schema=2)
    with pytest.raises(ValueError, match="SCHEMA"):
        net.load(p2, expect_schema=3)
    # compat-guard PPO: v2-весы в v3-контур и наоборот — RuntimeError
    with pytest.raises(RuntimeError, match="схем"):
        rl_setup._guard_compat(net.load(p2), net.Config(schema=3, hidden=8, head=6), p2)
    with pytest.raises(RuntimeError, match="схем"):
        rl_setup._guard_compat(net.load(p3), net.Config(schema=2, hidden=8, head=6), p3)


def test_load_still_rejects_unknown_schema(tmp_path):
    import json
    path = tmp_path / "weird.json"
    path.write_text(json.dumps({"format": net.FORMAT, "schema": 7,
                                "config": {}, "params": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="SCHEMA"):
        net.load(str(path))
