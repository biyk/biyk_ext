# tests/test_explore.py — пошаговый перебор достижимых клеток и случайные прогулки.
import itertools

import pytest

from conftest import make_npc, make_scene_payload, make_weapon
from planner.action import ACTION_MOVE, ACTION_TARGET, ACTION_USE
from planner.context import BattleContext
from planner.explore import BruteForceExplorer, RandomExplorer
from planner.geometry import DIR_VECTORS, apply_moves, cell_distance


def adjacent_target_ctx():
    # B в клетке (4,4) по диагонали от A(0,0)
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 200, 200, disposition=1)]
    payload = {**make_scene_payload(npcs=npcs, weapons=[make_weapon("sword")]), "speed": 30}
    return BattleContext.from_payload(payload)


def test_brute_prefers_orthogonal_adjacent_over_truncated_diagonal():
    # quin-обрезка даёт 3×downright + атака (+4.24); перебор — ортогонального
    # соседa цели на дистанции 1.0 (+4.66), это и есть оптимум хода
    ctx = adjacent_target_ctx()
    best = max(BruteForceExplorer(ctx).enumerate(), key=lambda c: c.score)
    assert best.score > 34.3
    assert best.score == pytest.approx(30 + 5.657 - 1.0, abs=0.02)


def test_brute_moves_bounded_and_never_on_enemy_cell():
    ctx = adjacent_target_ctx()
    enemy = ctx.cell_of(ctx.hostile_targets()[0])
    for cand in BruteForceExplorer(ctx).enumerate():
        dirs = [a.conf["direction"] for a in cand.actions if a.action == ACTION_MOVE]
        assert len(dirs) <= ctx.speed_steps          # скорость хода не превышена
        end = apply_moves(ctx.src_cell, dirs)
        assert end != enemy                          # вставать на существо нельзя
        assert cand.actions[0].action == ACTION_TARGET
        last = cand.actions[-1]
        if last.action == ACTION_USE:                # атака только из досягаемости
            weapon = ctx.weapon(last.conf["itemId"])
            assert weapon is not None
            assert weapon.mode_at(cell_distance(end, enemy)) is not None


def test_brute_stop_and_attack_when_already_in_reach():
    # враг ортогонально сосед (50px): лучший ход — не двигаясь, сразу атаковать
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 50, 0, disposition=1)]
    payload = {**make_scene_payload(npcs=npcs, weapons=[make_weapon("sword")]), "speed": 30}
    ctx = BattleContext.from_payload(payload)
    candidates = list(BruteForceExplorer(ctx).enumerate())
    stationary = [c for c in candidates
                  if not any(a.action == ACTION_MOVE for a in c.actions)]
    assert stationary and stationary[0].actions[-1].action == ACTION_USE
    assert max(c.score for c in candidates) == pytest.approx(30.0)


def test_random_yields_legal_bounded_walks():
    import random

    ctx = adjacent_target_ctx()
    enemy = ctx.cell_of(ctx.hostile_targets()[0])
    explorer = RandomExplorer(ctx, rng=random.Random(42))
    seen = list(itertools.islice(explorer.enumerate(), 40))
    assert len(seen) == 40                           # источник бесконечный
    for cand in seen:
        dirs = [a.conf["direction"] for a in cand.actions if a.action == ACTION_MOVE]
        assert len(dirs) <= ctx.speed_steps
        assert set(dirs) <= set(DIR_VECTORS)
        end = apply_moves(ctx.src_cell, dirs)
        assert end != enemy
        if cand.actions[-1].action == ACTION_USE:
            weapon = ctx.weapon(cand.actions[-1].conf["itemId"])
            assert weapon.mode_at(cell_distance(end, enemy)) is not None


def test_explore_sources_empty_without_hostiles():
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("N", 450, 0, disposition=0)]
    ctx = BattleContext.from_payload({**make_scene_payload(npcs=npcs), "token": None})
    assert list(BruteForceExplorer(ctx).enumerate()) == []
    assert list(itertools.islice(RandomExplorer(ctx).enumerate(), 1)) == []
