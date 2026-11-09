# tests/test_arent_transfer_v5.py — partial-transfer v4->v5 (train._transfer_4_to_5) + parity.
#
# Ключевое утверждение: v5-сеть, собранная переносом v4-весов (ствол и три старые головы
# копируются ПОБИТОВО, прививается только свежая maneuver-голова), на ОДНИХ И ТЕХ ЖЕ признаках
# state/cells/targets/weapons воспроизводит logits/value v4-сети точно. Это гейт корректности:
# тёплый старт v5 начинает с политики v4, а maneuver-голова случайна — её и учит конвейер.
# Плюс: формы весов = dims5, param_count согласован, тёплый старт v4 в cfg.schema=5 проходит,
# а переноса v2/v3->v5 (не через v4) — нет (явная ошибка).
import pytest

from arent import backend, net, spec4, spec5, train


def _v4_model(hidden=8, head=6, seed=3):
    return backend.build(net.Config(schema=4, hidden=hidden, head=head, seed=seed), kind="pure")


def test_transfer_4_to_5_keeps_shared_and_adds_maneuver_head():
    v4 = _v4_model()
    d4, d5 = spec4.dims4(), spec5.dims5()
    cfg5 = net.Config(schema=5, hidden=v4.cfg.hidden, head=v4.cfg.head, seed=v4.cfg.seed)
    out = train._transfer_4_to_5(v4.params, cfg5)
    # общие блоки перенесены побитово (state/cell/target/weapon ширины v5 == v4)
    assert out["trunk1"] == v4.params["trunk1"]
    assert out["trunk2"] == v4.params["trunk2"] and out["valueW"] == v4.params["valueW"]
    for group in ("cells", "targets", "weapons"):
        assert out["headW"][group] == v4.params["headW"][group]
        assert out["headB"][group] == v4.params["headB"][group]
        assert out["headU"][group] == v4.params["headU"][group]
        assert out["headUB"][group] == v4.params["headUB"][group]
    # новая maneuver-голова присутвует и имеет форму dims5
    assert "maneuvers" in out["headW"]
    assert len(out["headW"]["maneuvers"]) == cfg5.head
    assert len(out["headW"]["maneuvers"][0]) == cfg5.head + d5["maneuver_feat"]
    # формы согласованы с dims5/dims4 (state/cell не выросли)
    assert d5["state"] == d4["state"] and d5["cell_feat"] == d4["cell_feat"]
    cfg4 = net.Config(schema=4, hidden=v4.cfg.hidden, head=v4.cfg.head)
    assert net.param_count(cfg5) > net.param_count(cfg4)      # v5 крупнее ровно на maneuver-голову


def _samples_shared_columns():
    """v4-пример и v5-пример: общие колонки идентичны; v5 дополнительно maneuver-слоты (нули)."""
    d4, d5 = spec4.dims4(), spec5.dims5()
    state = [((i % 7) - 3) / 10.0 for i in range(d4["state"])]
    cells = [[((s * 3 + c) % 5) / 10.0 for c in range(d4["cell_feat"])] for s in range(d4["cells"])]
    targets = [[((s * 2 + c) % 6) / 10.0 for c in range(d4["target_feat"])] for s in range(d4["targets"])]
    weapons = [[((s * 5 + c) % 4) / 10.0 for c in range(d4["weapon_feat"])] for s in range(d4["weapons"])]
    legal3 = [[[1 for _ in range(d4["weapons"])] for _ in range(d4["targets"])] for _ in range(d4["cells"])]
    s4 = {"schema": 4, "state": state, "cells": cells, "targets": targets, "weapons": weapons,
          "mask": {"cells": [1] * d4["cells"], "targets": [1] * d4["targets"],
                   "weapons": [1] * d4["weapons"]},
          "legal": legal3, "y": {"plan": 1, "target": 0, "weapon": 0}, "value": 0.2}
    man = [[0.0] * d5["maneuver_feat"] for _ in range(d5["maneuvers"])]
    s5 = {"schema": 5, "state": state, "cells": cells, "targets": targets, "weapons": weapons,
          "maneuvers": man,
          "mask": {"cells": [1] * d5["cells"], "targets": [1] * d5["targets"],
                   "weapons": [1] * d5["weapons"], "maneuvers": [1] * d5["maneuvers"]},
          "legal": legal3, "y": {"plan": 1, "target": 0, "weapon": 0, "maneuver": spec5.MANEUVER_NONE},
          "value": 0.2}
    return s4, s5


def test_transferred_v5_reproduces_v4_logits_and_value():
    v4 = _v4_model()
    cfg5 = net.Config(schema=5, hidden=v4.cfg.hidden, head=v4.cfg.head, seed=v4.cfg.seed)
    params5 = train._transfer_4_to_5(v4.params, cfg5)
    v5 = backend.build(cfg5, kind="pure", params=params5)
    s4, s5 = _samples_shared_columns()
    c4, t4, w4, val4 = v4.head_logp(s4)
    c5, t5, w5, val5 = v5.head_logp(s5)         # тот же 4-tuple (без maneuver-головы)
    assert c5 == pytest.approx(c4) and t5 == pytest.approx(t4) and w5 == pytest.approx(w4)
    assert val5 == pytest.approx(val4)
    # maneuver-голова отдельна и случайна: all_head_logp отдаёт 5-й вектор, не трогая остальные
    c5b, t5b, w5b, m5, val5b = v5.all_head_logp(s5)
    assert len(m5) == spec5.dims5()["maneuvers"]
    assert c5b == pytest.approx(c4) and val5b == pytest.approx(val4)


def test_warm_params_allows_v4_into_v5_and_rejects_wrong_shape(tmp_path):
    v4 = _v4_model()
    path = net.save(v4, str(tmp_path / "v4.json"), metrics={"n": 1})
    cfg5 = net.Config(schema=5, hidden=v4.cfg.hidden, head=v4.cfg.head)
    params, warm_from, from_schema = train._warm_params(cfg5, path)
    assert from_schema == 4 and warm_from == path
    assert "maneuvers" in params["headW"]
    assert len(params["headW"]["maneuvers"][0]) == cfg5.head + spec5.dims5()["maneuver_feat"]
    # несовместимый hidden -> явная ошибка (перенос сохраняет hidden/head-форму)
    cfg_bad = net.Config(schema=5, hidden=v4.cfg.hidden + 4, head=v4.cfg.head)
    with pytest.raises(RuntimeError, match="форм"):
        train._warm_params(cfg_bad, path)
    # схема 3 в схему 5 (не через v4) -> transfer не определён -> явная ошибка схемы
    v3 = backend.build(net.Config(schema=3, hidden=v4.cfg.hidden, head=v4.cfg.head), kind="pure")
    p3 = net.save(v3, str(tmp_path / "v3.json"))
    with pytest.raises(RuntimeError, match="несовместим"):
        train._warm_params(net.Config(schema=5, hidden=v3.cfg.hidden, head=v3.cfg.head), p3)
