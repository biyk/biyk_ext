# tests/test_spec3_feat_version.py — несовместимость артефактов при bump 2->3 (Этап 4).
#
# Добавление coverLos/atChokeEnd подняло FEATURES_VERSION 2->3 (ширина головы 21->23). Это
# значит: сохранённые ЧЕКПОЙНТЫ и ДАТАСЕТЫ версии v2 обязаны ОТВЕРГАТЬСЯ при загрузке явно,
# а не молча давать мусор — иначе warm-start Этапа 4 с прежних весов был бы тихой ошибкой.
import json

import pytest

from arent import backend, dataset, net, spec3


def test_features_version_is_bumped_to_three():
    assert spec3.FEATURES_VERSION == 3
    assert len(spec3.CELL3_FEATURES) == 23


def test_v2_checkpoint_is_rejected(tmp_path):
    cfg = net.Config(schema=3, hidden=8, head=6)
    model = backend.build(cfg, kind="pure")
    path = str(tmp_path / "v3.json")
    net.save(model, path)
    ckpt = json.load(open(path, encoding="utf-8"))
    # прежняя конфигурация (до Этапа 4): feat_version=2, cell_feat=21
    old = dict(ckpt)
    old["dims"] = dict(ckpt["dims"], cell_feat=21, feat_version=2)
    p_old = str(tmp_path / "old_v2.json")
    json.dump(old, open(p_old, "w", encoding="utf-8"))
    with pytest.raises(ValueError, match="несовместим"):
        net.load(p_old, expect_schema=3)


def test_v2_dataset_row_is_rejected(tmp_path):
    row = {"schema": 3, "feat_version": 2,
           "cells": [[0.0] * 21 for _ in range(spec3.K_MOVEPLAN + 1)],
           "y": {"plan": 0, "target": 0, "weapon": 0}}
    p = tmp_path / "old.jsonl"
    p.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(dataset.SchemaMismatch):
        dataset.load(str(p))


def test_current_v3_row_is_accepted(tmp_path):
    row = {"schema": 3, "feat_version": spec3.FEATURES_VERSION,
           "cells": [[0.0] * len(spec3.CELL3_FEATURES) for _ in range(spec3.K_MOVEPLAN + 1)],
           "y": {"plan": 0, "target": 0, "weapon": 0}}
    p = tmp_path / "new.jsonl"
    p.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert len(dataset.load(str(p))) == 1
