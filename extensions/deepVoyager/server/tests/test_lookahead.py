# tests/test_lookahead.py — многошаговый расчёт (пункт 5): итеративное углубление
# с топ-K первыми вариантами и жадными ответами врагов.
#
# Проверяем три вещи: что плоский режим не изменился (regression), что глубина
# меняет решение там, где враги наказывают за жадность, и что дедлайн соблюдается
# (худший случай — сегодняшний перебор, он остаётся фолбэком).
import dataclasses
import random
import time

import pytest

from conftest import make_npc, make_scene_payload, make_weapon
from planner.action import ACTION_TARGET
from planner.context import BattleContext
from planner.lookahead import FirstLayer, Lookahead
from planner.points import default_tuning, set_tuning, tuning
from planner.service import PlannerService
from planner.sim import rollout
from planner.strategy import StrategyEnumerator

SWORD = make_weapon("sword", damage="1d6+2")       # ожидание 5.5, со шансом 3.575


def arena(e1_hp=1, e2_hp=30):
    """Герой в (0,5); E1 в (0,3) с hp 1 — «убить и не получить ответки»;
    E2 в (0,9) — живучая и дальняя цель. Оба врага ходят по 1 клетке за раунд.
    """
    npcs = [make_npc("A", 250, 0, disposition=-1, hp=30),
            make_npc("E1", 150, 0, disposition=1, hp=e1_hp, speed=5, damage="1d8"),
            make_npc("E2", 450, 0, disposition=1, hp=e2_hp, speed=5, damage="1d8")]
    return BattleContext.from_payload({**make_scene_payload(npcs=npcs, weapons=[SWORD],
                                                            token="E1"), "speed": 30})


def plan(context, rounds=1, limit=None, top_k=None, shallow_k=None):
    values = {"max_rounds": rounds}
    if top_k is not None:
        values["top_k"] = top_k
    if shallow_k is not None:
        values["shallow_k"] = shallow_k
    set_tuning(dataclasses.replace(default_tuning(), **values))
    # после screening должно остаться время на дерево: иначе на загруженной машине
    # глубина 2 не успевает раскрыться и план откатывается к greedy
    budget = limit if limit is not None else (0.5 if rounds == 1 else 1.5)
    return PlannerService(time_limit_sec=budget, rng=random.Random(0)).plan_result(context)


def first_target(result):
    return next(a.conf["id"] for a in result.actions if a.action == ACTION_TARGET)


def dicts(result):
    return [a.to_dict() for a in result.actions]


def test_flat_mode_reports_only_score():
    result = plan(arena())
    assert result.depth == 1 and result.nodes == 0
    assert result.report == ""
    assert result.value == pytest.approx(result.score)


def test_without_depth_npc_charges_the_survivable_far_foe():
    # жадность меряет только текущий раунд: сближение 3 + уверенная атака = 33
    result = plan(arena())
    assert first_target(result) == "E2"
    assert result.score == pytest.approx(33.0)


def test_with_depth_npc_kills_the_immediate_threat_instead():
    # E1 умирает с одного удара и не бьёт в ответ, подход к E2 стоит −19.5 в раунде
    result = plan(arena(), rounds=2)
    assert result.depth == 2
    assert first_target(result) == "E1"


def test_search_value_equals_independent_rollout():
    result = plan(arena(), rounds=2)
    assert result.value == pytest.approx(rollout(arena(), result.actions, 2), abs=0.02)


def test_deep_line_rolls_out_better_than_greedy_line():
    greedy = plan(arena())
    deep = plan(arena(), rounds=2)
    assert rollout(arena(), deep.actions, 2) > rollout(arena(), greedy.actions, 2)


def test_report_lists_every_round_and_the_total():
    result = plan(arena(), rounds=2)
    assert "R1" in result.report and "R2" in result.report
    assert result.report.rstrip().endswith(f"= {result.value:g}")


def test_no_time_left_falls_back_to_the_flat_plan():
    deep = plan(arena(), rounds=3, limit=0.0)
    flat = plan(arena(), rounds=1, limit=0.0)
    assert deep.depth == 1                      # времени нет — остаёмся на greedy
    assert dicts(deep) == dicts(flat)


def test_top_k_one_expands_only_the_best_greedy_candidate():
    deep = plan(arena(), rounds=2, top_k=1)
    flat = plan(arena(), rounds=1)
    assert first_target(deep) == first_target(flat)   # ветвиться не с чего другого
    assert deep.depth == 2


def test_deeper_search_opens_at_least_as_many_nodes():
    two = plan(arena(), rounds=2, limit=2.0)
    three = plan(arena(), rounds=3, limit=2.0)
    assert two.nodes > 0
    assert three.nodes >= two.nodes
    assert three.depth >= two.depth


def test_foe_that_survives_keeps_its_threat_in_the_value():
    killed = plan(arena(e1_hp=1), rounds=2)
    survived = plan(arena(e1_hp=30), rounds=2)
    assert killed.value > survived.value


def test_search_is_deterministic():
    a = plan(arena(), rounds=2)
    b = plan(arena(), rounds=2)
    assert dicts(a) == dicts(b)
    assert a.value == pytest.approx(b.value)


def test_shallow_k_limits_deeper_branching():
    # дерево вызываем напрямую: через сервис узлы считались бы после минуты screening
    def tree(shallow_k):
        set_tuning(dataclasses.replace(default_tuning(), max_rounds=3, top_k=1,
                                       shallow_k=shallow_k))
        ctx = arena()
        layer = FirstLayer(top_k=1)
        for candidate in StrategyEnumerator(ctx).enumerate():
            layer.add(candidate, ctx.src_cell)
        return Lookahead(ctx, deadline=time.monotonic() + 5.0).search(layer.roots())

    narrow, wide = tree(1), tree(4)
    assert narrow.depth == 3 and wide.depth == 3
    assert narrow.nodes < wide.nodes


def test_scene_without_hostiles_stays_flat_and_empty():
    npcs = [make_npc("A", 0, 0, disposition=-1, hp=10),
            make_npc("N", 200, 0, disposition=0, hp=5)]
    ctx = BattleContext.from_payload({**make_scene_payload(npcs=npcs, token=None)})
    result = plan(ctx, rounds=3)
    assert result.actions == [] and result.depth == 1


def test_default_tuning_keeps_single_round_behaviour():
    set_tuning(default_tuning())
    assert tuning().max_rounds == 1
    result = PlannerService(time_limit_sec=0.5, rng=random.Random(0)).plan_result(arena())
    assert result.depth == 1 and result.report == ""
