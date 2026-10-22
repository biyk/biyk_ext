# tests/test_arent_battlecast.py — портированный battlecast-учитель: legality/roundtrip/шкала.
#
# Покрываем пункты ТЗ этапа 2: выбранные действия допустимы; декодирование возвращает
# ровно тот план, что выбрал учитель; пример пишется в текущий JSONL; value лежит на
# НАШЕЙ шкале (rollout), а не на внутренней сумме эвристик. Плюс чистый тест фокус-огня
# (добить раненого) и guard честности: неподдерживаемые механики заявлены списком.
import pytest

from arent import paths, spec
from arent import slots as slots_mod
from arent.battlecast import BattlecastTeacher
from arent.battlecast_heuristics import (Enemy, UNSUPPORTED_MECHANICS, best_strike,
                                         expected_hit_damage, incoming_at_cell)
from arent.dataset import generate, sample_one
from arent.observe import observe
from arent.teacher import pinned
from arent.teachers import get_teacher, list_teachers
from playground.arena import load_arena
from planner.armament import Weapon
from planner.explore import reachable_paths
from planner.pathfinding import PathfindingService
from planner.points import tuning
from planner.turns import rollout


def test_battlecast_is_registered_and_constructible():
    assert "battlecast" in list_teachers()
    assert isinstance(get_teacher("battlecast", rounds=1, time_limit_sec=0.5), BattlecastTeacher)


def _corridor():
    return load_arena("corridor_archer")


def test_battlecast_sample_is_producible_and_jsonl_ready(tmp_path):
    """sample_one с battlecast даёт готовый пример — т.е. план легален и декодируется."""
    paths.set_workspace(str(tmp_path))
    payload = _corridor()
    teacher = get_teacher("battlecast", rounds=1, time_limit_sec=0.5)
    with pinned(rounds=1, time_limit_sec=0.5):
        sample, reason = sample_one("corridor_archer", payload, teacher, {"src": payload["src"]})
    assert reason == "ok", reason
    assert set(sample) == {"schema", "state", "cells", "targets", "weapons", "mask", "legal",
                           "y", "value", "meta"}
    # метка реального учителя обязана лежать в A(s) (с учётом канона no-attack)
    from arent import joint
    assert joint.ensure_jointly_legal(sample, sample["schema"])


def test_battlecast_chosen_actions_pass_our_legality_check():
    payload = _corridor()
    teacher = get_teacher("battlecast", rounds=1, time_limit_sec=0.5)
    labeled = teacher.label(payload)
    ctx = labeled.ctx
    from planner.action import ACTION_MOVE, ACTION_TARGET, ACTION_USE
    from planner.geometry import apply_moves, DIR_VECTORS

    paths_by_cell = reachable_paths(PathfindingService(ctx)._finder, ctx.src_cell,
                                    ctx.src_id, ctx.speed_steps)
    assert paths_by_cell                       # наш BFS вернул достижимые клетки
    hostiles = {t.id for t in ctx.hostile_targets()}
    weapons = {w.id for w in ctx.weapons}
    dirs = [a.conf["direction"] for a in labeled.actions if a.action == ACTION_MOVE]
    assert all(d in DIR_VECTORS for d in dirs)
    final = apply_moves(ctx.src_cell, dirs)
    assert final in paths_by_cell              # клетка достижима легальным маршрутом
    targets = [a.conf["id"] for a in labeled.actions if a.action == ACTION_TARGET]
    assert all(t in hostiles for t in targets)
    uses = [a.conf["itemId"] for a in labeled.actions if a.action == ACTION_USE]
    assert all(u in weapons for u in uses)


def test_battlecast_decode_equals_the_chosen_plan():
    payload = _corridor()
    teacher = get_teacher("battlecast", rounds=1, time_limit_sec=0.5)
    labeled = teacher.label(payload)
    ctx, obs = labeled.ctx, observe(labeled.ctx)
    slots = slots_mod.build(ctx, obs)
    slots_mod.ensure_cell(slots, ctx.src_cell, slots_mod.final_cell(ctx, labeled.actions),
                          slots_mod.dirs_of(labeled.actions))
    label = slots_mod.label_of(ctx, slots, labeled.actions)
    assert label is not None
    decoded = [a.to_dict() for a in slots_mod.decode(slots, label)]
    assert decoded == [a.to_dict() for a in labeled.actions]


def test_battlecast_value_is_our_rollout_scale_not_internal():
    """value обязан равняться rollout нашей симуляции, а не внутренней сумме эвристик."""
    payload = _corridor()
    teacher = get_teacher("battlecast", rounds=1, time_limit_sec=0.5)
    with pinned(rounds=1, time_limit_sec=0.5):
        labeled = teacher.label(payload)
    expected = rollout(labeled.ctx, labeled.actions, teacher.value_rounds)
    assert labeled.value == pytest.approx(expected)
    assert abs(labeled.value) <= 1e6           # это очки планировщика, а не сырой EV-суммарник


def test_generate_with_battlecast_records_teacher(tmp_path):
    paths.set_workspace(str(tmp_path))
    with pinned(rounds=1, time_limit_sec=0.5):
        samples, stats = generate(count=3, seed=4, per_src=1, rounds_max=0, teacher="battlecast",
                                  teacher_rounds=1, want_arenas=["corridor_archer", "fork_two_melee",
                                                                "glass_cannon"], use_live=False)
    assert stats["teacher"] == "battlecast"
    assert all(s["schema"] == spec.SCHEMA for s in samples)


def test_best_strike_focuses_on_dying_enemy():
    """Портированный приоритет: раненый, которого можно добить, бьётся первым."""
    weapons = [Weapon(id="m", name="меч", damage="1d8+2", attack_bonus=3, sure_ft=30, doubt_ft=30)]
    enemies = [Enemy(id="C", cell=(0, 3), hp=40, ac=12, dmg_to_me=4, reach_cells=1, speed_cells=6),
               Enemy(id="B", cell=(0, 1), hp=1, ac=12, dmg_to_me=4, reach_cells=1, speed_cells=6)]
    enemy, weapon, ev = best_strike((0, 0), enemies, weapons, tuning().hit_chance)
    assert enemy.id == "B"
    assert ev > expected_hit_damage(weapon, enemies[0].ac, tuning().hit_chance)  # + finish-бонус


def test_incoming_at_cell_counts_only_reachable_threats():
    far = Enemy(id="F", cell=(0, 10), hp=10, ac=12, dmg_to_me=5, reach_cells=1, speed_cells=6)
    near = Enemy(id="N", cell=(0, 1), hp=10, ac=12, dmg_to_me=5, reach_cells=1, speed_cells=6)
    assert incoming_at_cell((0, 0), [far, near]) == pytest.approx(5.0)


def test_unsupported_mechanics_are_declared_not_faked():
    """Guard честности: то, чего нет в нашей симуляции, честно числится неподдержанным."""
    for mechanic in ("resistance/vulnerability/immunity", "conditions", "aoe_spells",
                     "opportunity_attacks", "int_modifier_strategy_choice"):
        assert mechanic in UNSUPPORTED_MECHANICS
