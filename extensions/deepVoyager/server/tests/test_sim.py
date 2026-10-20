# tests/test_sim.py — симуляция одного раунда (пункт 5): движение, урон, ответ врагов.
#
# Ключевая идея: отдельной модели боя нет — Simulation пересобирает BattleContext,
# поэтому Scorer/best_strike/quin работают на симулированной позиции как на живой.
import pytest

from conftest import make_npc, make_scene_payload, make_weapon
from planner.action import move_action, target_action, use_action
from planner.context import BattleContext
from planner.points import tuning
from planner.scoring import Scorer
from planner.sim import Simulation, rollout

DAMAGE_SWORD = "1d6+2"                 # ожидание 5.5, с hitChance 0.65 -> 3.575


def ctx_of(npcs, weapons=None, speed=30, token="B"):
    payload = {**make_scene_payload(npcs=npcs, weapons=weapons or []), "speed": speed,
               "token": token}
    return BattleContext.from_payload(payload)


def hero_and_foe(foe_x=50, foe_hp=10, foe_speed=30, foe_damage="1d8", token="B"):
    """Герой A в (0,0); враг B в клетке (0, foe_x/50); нейтральный N рядом с героем."""
    npcs = [make_npc("A", 0, 0, disposition=-1, hp=20),
            make_npc("B", foe_x, 0, disposition=1, hp=foe_hp, speed=foe_speed,
                     damage=foe_damage),
            make_npc("N", 0, 50, disposition=0, hp=5)]
    return ctx_of(npcs, weapons=[make_weapon("sword", damage=DAMAGE_SWORD)], token=token)


def test_sim_of_exposes_hero_and_hostiles():
    sim = Simulation.of(hero_and_foe())
    assert sim.hero.id == "A" and sim.hero.cell == (0, 0)
    assert [f.id for f in sim.foes] == ["B"]          # нейтральный не враг
    assert sim.hp["B"] == 10


def test_apply_hero_moves_and_rebuilds_context():
    sim = Simulation.of(hero_and_foe(foe_x=200))
    after = sim.apply_hero([target_action("B"), move_action("right")])
    assert after.cells["A"] == (0, 1)
    # пересобранный контекст — тот же источник истины для скорера и quin
    assert after.context_for("A").src_cell == (0, 1)
    assert after.context_for("A").cell_of(after.context_for("A").token("B")) == (0, 4)


def test_hero_attack_applies_expected_damage_scaled_by_hit_chance():
    sim = Simulation.of(hero_and_foe())
    after = sim.apply_hero([target_action("B"), use_action("sword")])
    assert after.hp["B"] == pytest.approx(10 - 5.5 * tuning().hit_chance)
    assert after.base is sim.base             # исходный контекст не мутируется


def test_dead_enemy_stops_being_a_foe():
    sim = Simulation.of(hero_and_foe(foe_hp=1))
    after = sim.apply_hero([target_action("B"), use_action("sword")])
    assert after.foes == ()
    assert after.context_for("A").hostile_targets() == []


def test_foe_closes_in_and_hits():
    sim = Simulation.of(hero_and_foe(foe_x=100))     # враг в 2 клетках, ход 6
    after, penalty = sim.foes_act()
    assert penalty == pytest.approx(tuning().damage_penalty * tuning().hit_chance)
    assert after.cells["B"] == (0, 1)                 # вплотную, но не на клетке героя
    assert after.hp["A"] == pytest.approx(20 - 4.5 * tuning().hit_chance)


def test_foe_too_far_and_too_slow_does_not_hit():
    sim = Simulation.of(hero_and_foe(foe_x=450, foe_speed=5))
    after, penalty = sim.foes_act()
    assert penalty == 0.0
    assert after.cells["B"] == (0, 8)                 # один шаг сближения
    assert after.hp["A"] == 20


def test_death_penalty_when_hero_cannot_survive_the_blow():
    ctx = ctx_of([make_npc("A", 0, 0, disposition=-1, hp=1),
                  make_npc("B", 50, 0, disposition=1, hp=20, damage="2d6+3")],
                 weapons=[make_weapon("sword", damage=DAMAGE_SWORD)])
    after, penalty = Simulation.of(ctx).foes_act()
    # сам удар — с вероятностью попадания, гибель — безусловный штраф
    assert penalty == pytest.approx(tuning().damage_penalty * tuning().hit_chance
                                   + tuning().death_penalty)
    assert after.hero_dead is True
    assert after.hp["A"] <= 0


def test_round_value_is_first_round_score_plus_enemy_penalty():
    ctx = hero_and_foe()
    sim = Simulation.of(ctx)
    actions = [target_action("B"), use_action("sword")]
    _after, penalty = sim.foes_act()
    assert sim.round_value(actions) == pytest.approx(Scorer().score(ctx, actions) + penalty)


def test_rollout_one_round_equals_round_value():
    ctx = hero_and_foe()
    sim = Simulation.of(ctx)
    actions = [target_action("B"), use_action("sword")]
    assert rollout(ctx, actions, 1) == pytest.approx(sim.round_value(actions))


def test_rollout_accumulates_several_rounds():
    # никто никого не достает: каждый раунд только сближение на 1 клетку (+1 очко)
    ctx = ctx_of([make_npc("A", 0, 0, disposition=-1, hp=20),
                  make_npc("B", 450, 0, disposition=1, hp=20, speed=5, damage="1d8")],
                 weapons=[make_weapon("sword", sure_ft=5, damage=DAMAGE_SWORD)], speed=5)
    assert rollout(ctx, [target_action("B"), move_action("right")], 3) == pytest.approx(3.0)


def test_unit_parameters_come_from_payload_fields():
    ctx = hero_and_foe(foe_x=100, foe_speed=10, foe_damage="2d6")
    foe = Simulation.of(ctx).foes[0]
    assert (foe.speed_steps, foe.damage_avg, foe.reach_cells) == (2, 7.0, 1.0)
    assert foe.chance == pytest.approx(0.65)          # hitChance не прислали -> дефолт


def test_explicit_hit_chance_overrides_default():
    npcs = [make_npc("A", 0, 0, disposition=-1, hp=20),
            make_npc("B", 50, 0, disposition=1, hp=20, damage="1d8", hit_chance=0.5)]
    foe = Simulation.of(ctx_of(npcs, weapons=[make_weapon("sword")])).foes[0]
    assert foe.chance == 0.5


def test_foes_act_skips_dead_and_uses_their_own_reach():
    # враг с reach 10 футов (2 клетки) бьет, не сходя с места
    npcs = [make_npc("A", 0, 0, disposition=-1, hp=20),
            make_npc("B", 100, 0, disposition=1, hp=20, damage="1d8", reach_ft=10, speed=5)]
    after, penalty = Simulation.of(ctx_of(npcs)).foes_act()
    assert penalty == pytest.approx(tuning().damage_penalty * tuning().hit_chance)
    assert after.cells["B"] == (0, 2)
