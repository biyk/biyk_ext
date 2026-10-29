# tests/test_arent_net_schema_v4.py — контракт SCHEMA=4: ширины/профиль/инициализация/перенос-guard.
#
# v4 = v3 (move-plan голова) + экномика действий/Ao: state += RESOURCE_FEATURES (хвост после
# grid), cell_feat += 2 (provokesAo/aoRisk), weapon_feat += 3 (isAction/isBonus/isReaction, только
# head оружия). Проверяем: профиль dims/slot_size/y_key для схемы 4, init_params/param_count по
# схеме 4, pure-политик обучается/предсказывает на v4-выборке, save/load, и что _check_feature_compat
# ОТВЕРГАЕТ чекпойнт схемы 4 со СТАРЫМИ ширинами (симулируем v3-dims в v4-обёртке) явно.
import copy

import pytest

from arent import backend, net, spec, spec3, spec4


def _v4_sample():
    d = spec4.dims4()
    return {
        "schema": 4, "state": [0.1] * d["state"],
        "cells": [[0.1] * d["cell_feat"] for _ in range(d["cells"])],
        "targets": [[0.1] * d["target_feat"] for _ in range(d["targets"])],
        "weapons": [[0.1] * d["weapon_feat"] for _ in range(d["weapons"])],
        "mask": {"cells": [1] * d["cells"], "targets": [1] * d["targets"],
                 "weapons": [1] * d["weapons"]},
        "legal": [[[1 for _ in range(d["weapons"])] for _ in range(d["targets"])]
                  for _ in range(d["cells"])],
        "y": {"plan": 0, "target": 0, "weapon": 0},
        "value": 0.3, "meta": {"arena": "gen_x"},
    }


def test_spec4_contracts_widths():
    # v4-признаки = v3 + Ao-колонки; head оружия = v2 + 3 флага; state = v2 + хвост ресурсов
    assert spec4.SCHEMA == 4
    assert spec4.CELL4_FEATURES == spec3.CELL3_FEATURES + ("provokesAo", "aoRisk")
    assert spec4.WEAPON_FEATURES4 == spec.WEAPON_FEATURES + ("isAction", "isBonus", "isReaction")
    assert spec4.RESOURCE_FEATURES == ("actionRemaining", "bonusRemaining", "reactionRemaining")
    d4 = spec4.dims4()
    base = spec.dims()
    assert d4["cell_feat"] == len(spec3.CELL3_FEATURES) + 2
    assert d4["weapon_feat"] == len(spec.WEAPON_FEATURES) + 3
    assert d4["state"] == base["state"] + len(spec4.RESOURCE_FEATURES)
    assert d4["grid"] == base["grid"]                       # grid не сдвигается (перенос по хвосту)
    assert d4["cells"] == spec3.K_MOVEPLAN + 1 and d4["targets"] == base["targets"]
    assert d4["feat_version"] == spec4.FEATURES_VERSION


def test_uses_moveplan_covers_v3_and_v4():
    assert spec3.uses_moveplan(3) and spec3.uses_moveplan(4)
    assert not spec3.uses_moveplan(2)


def test_profile_and_slot_size_schema4():
    assert net.dims_for(4) == spec4.dims4()
    assert net.slot_size("cells", 4) == len(spec4.CELL4_FEATURES)
    assert net.slot_size("weapons", 4) == len(spec4.WEAPON_FEATURES4)
    assert net.slot_size("targets", 4) == len(spec.ENEMY_FEATURES)     # цели общие с v2/v3
    assert net.y_key(4)["cells"] == "plan" and net.y_key(4)["weapons"] == "weapon"
    assert net.feature_version(4) == spec4.FEATURES_VERSION


def test_init_params_and_param_count_track_schema4():
    cfg4 = net.Config(schema=4, hidden=8, head=6)
    p4 = net.init_params(cfg4)
    assert len(p4["trunk1"][0]) == spec4.dims4()["state"]
    assert len(p4["headW"]["cells"][0]) == cfg4.head + len(spec4.CELL4_FEATURES)
    assert len(p4["headW"]["weapons"][0]) == cfg4.head + len(spec4.WEAPON_FEATURES4)
    assert len(p4["headW"]["targets"][0]) == cfg4.head + len(spec.ENEMY_FEATURES)
    assert net.param_count(cfg4) == net.param_count(cfg4, spec4.dims4())


def test_pure_policy_trains_and_saves_schema4(tmp_path):
    cfg = net.Config(schema=4, hidden=8, head=6, epochs=1)
    model = backend.build(cfg, kind="pure")
    sample = _v4_sample()
    report = model.step_batch([sample], lr=0.1)
    assert "plan" in report
    out = model.predict(sample)
    assert "plan" in out and "cell" not in out
    assert net.y_index(sample, "cells", 4) == 0
    path = net.save(model, str(tmp_path / "m4.json"), metrics={"n": 1})
    ckpt = net.load(path, expect_schema=4)
    assert ckpt["schema"] == 4 and ckpt["dims"] == spec4.dims4()
    again = backend.load_policy(path, kind="pure")
    assert "plan" in again.predict(sample)


def test_v4_guard_rejects_stale_widths(tmp_path):
    # good v4 checkpoint loads clean
    model = backend.build(net.Config(schema=4, hidden=8, head=6), kind="pure")
    good = net.save(model, str(tmp_path / "m4.json"))
    assert net.load(good, expect_schema=4)["schema"] == 4
    # stale v4: dims с v3-ширинами (cell_feat/state/weapon_feat старые) -> ValueError явно
    ckpt = net.load(good, expect_schema=4)
    bad = copy.deepcopy(ckpt)
    bad["dims"] = spec3.dims3()                     # прежние ширины при схеме 4
    bad["schema"] = 4
    with pytest.raises(ValueError, match="v4"):
        net._check_feature_compat(bad, "тест")
    # wrong feat_version тоже отвергается
    bad2 = copy.deepcopy(ckpt)
    bad2["dims"] = dict(spec4.dims4(), feat_version=99)
    with pytest.raises(ValueError, match="v4"):
        net._check_feature_compat(bad2, "тест")
