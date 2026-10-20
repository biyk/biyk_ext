# tests/test_arent_split.py — групповой split: утечка сценариев и точных дубликатов.
#
# Проверяем инварианты, ради которых пишется этот код: варианты одного снимка не
# разъезжаются по разные стороны, одинаковые состояния не пересекают границу, split
# детерминирован по seed, а без meta.arena он не притворяется безопасным.
import pytest

from arent import spec
from arent.splitting import UnsafeSplit, group_arenas, split_grouped, state_signature


def make(arena=None, state_val=0.0, src="A", variant=0):
    d = spec.dims()
    meta = {"src": src, "variant": variant}
    if arena is not None:
        meta["arena"] = arena
    return {"schema": spec.SCHEMA, "state": [state_val] * d["state"],
            "cells": [[0.0] * d["cell_feat"] for _ in range(d["cells"])],
            "targets": [[0.0] * d["target_feat"] for _ in range(d["targets"])],
            "weapons": [[0.0] * d["weapon_feat"] for _ in range(d["weapons"])],
            "mask": {"cells": [1] * d["cells"], "targets": [1] * d["targets"],
                     "weapons": [1] * d["weapons"]},
            "y": {"cell": 0, "target": 0, "weapon": 0}, "value": 0.0, "meta": meta}


def scenario(arena, k):
    """k производных одного снимка: тот же arena, разные variant, состояние уникально."""
    base = sum(ord(c) for c in arena) * 1.0
    return [make(arena=arena, state_val=base + v / 100.0, variant=v) for v in range(k)]


def arenas_of(samples):
    return {(s["meta"] or {}).get("arena") for s in samples}


def test_grouped_split_keeps_every_scenario_on_one_side():
    pool = scenario("alpha", 4) + scenario("beta", 3) + scenario("gamma", 5)
    for seed in range(6):
        train, val, report = split_grouped(pool, frac=0.7, seed=seed)
        assert report["group_overlap"] == []
        assert not (arenas_of(train) & arenas_of(val))
        assert len(train) + len(val) == len(pool)
        assert report["train_samples"] == len(train) and report["val_samples"] == len(val)
        assert report["train_groups"] + report["val_groups"] == report["groups_total"]


def test_grouped_split_is_deterministic_per_seed():
    pool = scenario("a", 3) + scenario("b", 3) + scenario("c", 3) + scenario("d", 2)
    one = split_grouped(pool, frac=0.6, seed=11)
    two = split_grouped(pool, frac=0.6, seed=11)
    assert [id_map(t) for t in one[0]] == [id_map(t) for t in two[0]]
    assert one[2]["train_group_keys"] == two[2]["train_group_keys"]


def id_map(sample):
    m = sample["meta"]
    return (m.get("arena"), m.get("variant"))


def test_grouped_split_leaves_no_exact_state_across_the_boundary():
    dup = make(arena="x", state_val=0.5)
    twin = make(arena="y", state_val=0.5)               # то же состояние, другой снимок
    assert state_signature(dup) == state_signature(twin)
    pool = [dup, twin] + scenario("z", 4) + scenario("w", 4)
    for seed in range(5):
        train, val, report = split_grouped(pool, frac=0.6, seed=seed)
        assert report["exact_state_overlap"] == []
        # x и y склеены union-find'ом -> они всегда по одну сторону
        assert (dup in train) == (twin in train)


def test_grouped_split_refuses_a_single_scenario():
    pool = scenario("only", 6)
    with pytest.raises(UnsafeSplit, match="групп"):
        split_grouped(pool, frac=0.7, seed=1)


def test_group_arenas_counts_independent_scenarios():
    pool = scenario("a", 3) + scenario("b", 2) + scenario("c", 4)
    roots = group_arenas(pool)
    assert len(roots) == 3                                  # три независимых снимка
    assert sorted(name for group in roots.values() for name in group) == ["a", "b", "c"]


def test_unlabeled_rows_warn_but_do_not_silently_pass_as_safe():
    pool = [make(arena=None, state_val=i / 10.0) for i in range(6)]
    train, val, report = split_grouped(pool, frac=0.6, seed=3)
    assert report["unlabeled_rows"] == 6 and report["warnings"]
    assert len(train) + len(val) == len(pool)


def test_strict_mode_refuses_missing_metadata():
    pool = [make(arena=None, state_val=0.1), make(arena=None, state_val=0.2),
            make(arena="x", state_val=0.3)]
    with pytest.raises(UnsafeSplit, match="meta.arena"):
        split_grouped(pool, frac=0.6, seed=1, strict=True)
