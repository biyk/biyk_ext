# tests/test_arent_transfer_v4.py — partial-transfer v3->v4 (train._transfer_3_to_4) + parity.
#
# Ключевое утверждение: v4-сеть, собранная переносом v3-весов (общие колонки скопированы, новые
# хвостовые — нули), на ПРИМЕРЕ С НУЛЕВЫМИ НОВЫМИ ПРИЗНАКАМИ воспроизводит logits/value v3-сети
# бит-в-бит. Это и есть гейт корректности переноса: дообучение стартует с той же политики, а
# новые признаки дают нулевой вклад, пока их не выучат. Плюс: формы весов = dims4, param_count
# согласован, несовместимый hidden/head отвергается явно.
import pytest

from arent import backend, net, spec, spec3, spec4, train


def _samples_with_zero_new_features():
    """v3-пример и v4-пример: общие колонки идентичны, новые (хвост state/cells/weapons) = 0."""
    d3, d4 = spec3.dims3(), spec4.dims4()
    state3 = [((i % 7) - 3) / 10.0 for i in range(d3["state"])]
    cells3 = [[((s * 3 + c) % 5) / 10.0 for c in range(d3["cell_feat"])] for s in range(d3["cells"])]
    targets3 = [[((s * 2 + c) % 6) / 10.0 for c in range(d3["target_feat"])] for s in range(d3["targets"])]
    weapons3 = [[((s * 5 + c) % 4) / 10.0 for c in range(d3["weapon_feat"])] for s in range(d3["weapons"])]
    legal = [[[1 for _ in range(d3["weapons"])] for _ in range(d3["targets"])] for _ in range(d3["cells"])]
    s3 = {"schema": 3, "state": state3, "cells": cells3, "targets": targets3, "weapons": weapons3,
          "mask": {"cells": [1] * d3["cells"], "targets": [1] * d3["targets"], "weapons": [1] * d3["weapons"]},
          "legal": legal, "y": {"plan": 1, "target": 0, "weapon": 0}, "value": 0.2}
    # v4 = те же колонки + нулевой хвост (3 ресурса в state, 2 в cell, 3 в weapon)
    s4 = {"schema": 4, "state": state3 + [0.0, 0.0, 0.0],
          "cells": [row + [0.0, 0.0] for row in cells3],
          "targets": [row[:] for row in targets3],
          "weapons": [row + [0.0, 0.0, 0.0] for row in weapons3],
          "mask": {"cells": [1] * d4["cells"], "targets": [1] * d4["targets"], "weapons": [1] * d4["weapons"]},
          "legal": legal, "y": {"plan": 1, "target": 0, "weapon": 0}, "value": 0.2}
    return s3, s4


def _v3_params(hidden=8, head=6):
    model = backend.build(net.Config(schema=3, hidden=hidden, head=head, seed=3), kind="pure")
    return model


def test_transfer_shapes_follow_dims4():
    v3 = _v3_params()
    d3, d4 = spec3.dims3(), spec4.dims4()
    out = train._transfer_3_to_4(v3.params, d3, d4, head=v3.cfg.head)
    assert len(out["trunk1"]) == v3.cfg.hidden
    assert len(out["trunk1"][0]) == d4["state"] == d3["state"] + len(spec4.RESOURCE_FEATURES)
    assert len(out["headW"]["cells"][0]) == v3.cfg.head + d4["cell_feat"]
    assert len(out["headW"]["weapons"][0]) == v3.cfg.head + d4["weapon_feat"]
    assert len(out["headW"]["targets"][0]) == v3.cfg.head + d4["target_feat"]
    # новые хвостовые колонки ровно нулевые (нейтральный вклад). headW row = [head | slot-признаки],
    # хвост признакам стоит ПОСЛЕ head-части -> нули начиная с head + old_slot_feat.
    head = v3.cfg.head
    assert all(row[d3["state"]:] == [0.0] * (d4["state"] - d3["state"]) for row in out["trunk1"])
    assert all(row[head + d3["cell_feat"]:] == [0.0] * 2 for row in out["headW"]["cells"])
    assert all(row[head + d3["weapon_feat"]:] == [0.0] * 3 for row in out["headW"]["weapons"])
    # побитово совпадающие блоки скопированы как есть
    assert out["headW"]["targets"] == v3.params["headW"]["targets"]
    assert out["trunk2"] == v3.params["trunk2"] and out["valueW"] == v3.params["valueW"]
    # param_count v4 = dims4-сумма
    cfg4 = net.Config(schema=4, hidden=v3.cfg.hidden, head=v3.cfg.head)
    assert net.param_count(cfg4) == net.param_count(cfg4, d4)


def test_transferred_v4_model_reproduces_v3_logits_on_zero_new_features():
    v3 = _v3_params()
    d3, d4 = spec3.dims3(), spec4.dims4()
    params4 = train._transfer_3_to_4(v3.params, d3, d4, head=v3.cfg.head)
    cfg4 = net.Config(schema=4, hidden=v3.cfg.hidden, head=v3.cfg.head, seed=v3.cfg.seed)
    v4 = backend.build(cfg4, kind="pure", params=params4)
    s3, s4 = _samples_with_zero_new_features()
    c3, t3, w3, val3 = v3.head_logp(s3)
    c4, t4, w4, val4 = v4.head_logp(s4)
    assert c4 == pytest.approx(c3) and t4 == pytest.approx(t3) and w4 == pytest.approx(w3)
    assert val4 == pytest.approx(val3)


def test_warm_params_allows_v3_into_v4_and_rejects_wrong_shape(tmp_path):
    v3 = _v3_params()
    path = net.save(v3, str(tmp_path / "v3.json"), metrics={"n": 1})
    cfg4 = net.Config(schema=4, hidden=v3.cfg.hidden, head=v3.cfg.head)
    params, warm_from, from_schema = train._warm_params(cfg4, path)
    assert from_schema == 3 and warm_from == path
    assert len(params["trunk1"][0]) == spec4.dims4()["state"]
    # несовместимый hidden -> явная ошибка (перенос сохраняет hidden/head-форму)
    cfg_bad = net.Config(schema=4, hidden=v3.cfg.hidden + 4, head=v3.cfg.head)
    with pytest.raises(RuntimeError, match="форм"):
        train._warm_params(cfg_bad, path)
    # schema=2 в schema=3 (не v4) -> transfer не определён -> явная ошибка схемы
    v2 = backend.build(net.Config(schema=2, hidden=v3.cfg.hidden, head=v3.cfg.head), kind="pure")
    p2 = net.save(v2, str(tmp_path / "v2.json"))
    with pytest.raises(RuntimeError, match="несовместим"):
        train._warm_params(net.Config(schema=3, hidden=v3.cfg.hidden, head=v3.cfg.head), p2)
