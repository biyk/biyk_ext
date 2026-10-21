# tests/test_arent_independent.py — резерв независимого набора (ho_*) держится в коде.
#
# Пункт 1 консультанта: честное сравнение bc2↔PPO требует сценариев, которые НИКОГДА не
# попадали ни в генерацию BC, ни в PPO train/val/reward/отбор чекпойнта. Резерв реализован
# префиксом ho_ и центрально в dataset. Здесь проверяем сами инварианты резерва:
#   1) распознавание префикса;
#   2) sources(exclude_independent=True) вычищает ho_*, обычный sources — оставляет;
#   3) independent_sources — ровно ho_* (тот же набор и для bc2, и для PPO);
#   4) обучение (generate/rl) всегда просит exclude_independent=True;
#   5) evaluate(independent=True) идёт только по ho_* и помечает тег "independent".
import json
import os

import pytest

from arent import backend, dataset, evaluate
from conftest import make_npc, make_scene_payload, make_weapon

ATTACK = {"cell": 0, "target": 0, "weapon": 0}


class StubPolicy:
    name = "stub"

    def predict(self, sample):
        return dict(ATTACK)


def _scene():
    hero = make_npc("A", 0, 0, disposition=-1, hp=50, speed=30, damage="1d8")
    foe = make_npc("B", 50, 0, disposition=1, hp=1, speed=0, damage="1d8")
    return make_scene_payload(npcs=[hero, foe], weapons=[make_weapon("sword")], token="B")


#--- 1. распознавание префикса -------------------------------------------------
def test_is_independent_matches_only_the_reserved_prefix():
    assert dataset.is_independent("ho_bridge_crossing") is True
    assert dataset.is_independent("ho_x") is True
    assert dataset.is_independent("ho2_line_00") is True     # командный holdout v2 тоже в резерве
    assert dataset.is_independent("ho3_line_00") is True     # независимый holdout схемы 3 в резерве
    for name in ("cap_20261019_live", "arena1_live", "bridge", "", "HO_uppercase", "ho2", "h2o_x", "ho3"):
        assert dataset.is_independent(name) is False


#--- 2/3. фильтрация источников -----------------------------------------------
def _patch_named_sources(monkeypatch, names):
    """Подменяем источники имён: арены + живые снимки одним списком (use_live irrelevant).

    dataset.sources делает `from playground import arena` внутри функции, поэтому латаем
    сам модуль arena.load_arena (он виден источникам), а не атрибут dataset.arena."""
    from playground import arena
    payload = _scene()
    monkeypatch.setattr(dataset, "arena_names", lambda want=None: list(names))
    monkeypatch.setattr(dataset, "payload_files", lambda: [])
    monkeypatch.setattr(arena, "load_arena", lambda name: payload)
    return payload


NAMES = ["arena1", "bridge", "ho_one", "ho2_line", "cap_live"]


def test_sources_include_ho_by_default(monkeypatch):
    _patch_named_sources(monkeypatch, NAMES)
    got = [n for n, _p in dataset.sources(use_live=False)]
    assert got == NAMES                                    # ничего не вычтено


def test_sources_exclude_independent_when_asked(monkeypatch):
    _patch_named_sources(monkeypatch, NAMES)
    got = [n for n, _p in dataset.sources(use_live=False, exclude_independent=True)]
    assert "ho_one" not in got and "ho2_line" not in got
    assert set(got) == {"arena1", "bridge", "cap_live"}


def test_independent_sources_is_exactly_the_reserved_set(monkeypatch):
    _patch_named_sources(monkeypatch, NAMES)
    got = [n for n, _p in dataset.independent_sources(use_live=False)]
    assert sorted(got) == ["ho2_line", "ho_one"]


def test_excluded_and_independent_are_disjoint_and_cover(monkeypatch):
    _patch_named_sources(monkeypatch, NAMES)
    train = {n for n, _p in dataset.sources(use_live=False, exclude_independent=True)}
    indep = {n for n, _p in dataset.independent_sources(use_live=False)}
    assert train & indep == set()                          # ни одна сцена не на обе стороны
    assert train | indep == set(NAMES)                      # вместе — весь пул


#--- 4. обучение всегда просит exclude_independent ----------------------------
def test_generate_asks_sources_to_exclude_independent(monkeypatch):
    seen = {}

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return iter([])                                    # пусто -> генерация завершится быстро

    monkeypatch.setattr(dataset, "sources", spy)
    samples, stats = dataset.generate(count=1, per_src=1, use_live=False)
    assert samples == []
    assert seen.get("exclude_independent") is True


def test_rl_run_requests_sources_with_exclude_independent(monkeypatch):
    """rl.run обязан звать sources(exclude_independent=True), иначе ho_* утекут в PPO."""
    from arent import rl
    calls = []

    def spy(want_arenas=None, use_live=True, exclude_independent=False):
        calls.append(exclude_independent)
        return iter([])                                    # пусто -> rl.run поднимется до Runtime

    monkeypatch.setattr(dataset, "sources", spy)
    with pytest.raises(RuntimeError):                      # нет сцен -> ожидаемое падение
        rl.run(name="x", iters=1, use_live=False)
    assert calls and all(c is True for c in calls)


#--- 5. evaluate(independent=True) идёт только по ho_* ------------------------
def test_evaluate_independent_restricts_to_reserved_set(tmp_path, monkeypatch):
    from arent import paths
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(backend, "load_policy", lambda path, kind="auto": StubPolicy())

    def fake_independent(want_arenas=None, use_live=True):
        return [("ho_one", _scene()), ("ho_two", _scene())]

    monkeypatch.setattr(dataset, "independent_sources", fake_independent)
    ckpt = paths.file_in(paths.run_dir("m"), "model.json")
    with open(ckpt, "w", encoding="utf-8") as f:
        f.write("{}")
    report = evaluate.run(name="ind", model_path=ckpt, independent=True, log=lambda *a: None)
    assert report["fights"] == 2
    names = {r["name"] for r in report["rows"]}
    assert names == {"ho_one", "ho_two"}
    out = os.path.join(str(tmp_path), "runs", "ind", "eval.json")
    with open(out, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["provenance"]["set_tag"] == "independent"
