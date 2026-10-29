# tests/test_action_economy_sim.py — SCHEMA=4 экномика действий и авто-Ao в симе (ЭТАП 2).
#
# Проверяем apply_actor_seq(..., reactions=True): атака по возможности (Ao) срабатывает ровно на
# ВЫХОДЕ актёра из melee-зоны живого врага с неподрашённой реакцией (урон ожиданием, реакция
# списывается, не более одного Ao); на ВХОД в зону — нет; при reaction=0 (напр. ranged-враг без
# реакции) — нет; USE списывает действие и блокируется, когда действий нет; reset_actor_turn
# откатывает ресурсы на своём ходу. С reactions=False (v2/v3) поведение бит-в-бит: два USE бьют
# оба, действие не тратится, Ao нет.
from dataclasses import replace

import pytest

from conftest import make_npc, make_scene_payload, make_weapon
from planner.action import move_action, target_action, use_action
from planner.context import BattleContext
from planner.points import tuning
from planner.sim import Simulation

DAMAGE_SWORD = "1d6+2"                 # ожидание 5.5; hitChance 0.65 -> удар 3.575
DAMAGE_FOE = "1d8"                      # враг: ожидание 4.5; Ao = 4.5 * 0.65 = 2.925


def _ctx():
    """Герой A в (0,0); враг B в клетке (0,1) вплотную (reach 1, реакция вооружена)."""
    npcs = [make_npc("A", 0, 0, disposition=-1, hp=20),
            make_npc("B", 50, 0, disposition=1, hp=20, damage=DAMAGE_FOE)]
    payload = {**make_scene_payload(npcs=npcs, weapons=[make_weapon("sword", damage=DAMAGE_SWORD)]),
               "speed": 30, "token": "A"}
    return BattleContext.from_payload(payload)


def _sim():
    sim = Simulation.of(_ctx())
    assert sim.units["B"].reaction == 1 and sim.units["B"].reach_cells == 1.0
    return sim


def test_ao_triggers_on_leaving_melee_zone():
    t = tuning()
    after = _sim().apply_actor_seq("A", [move_action("left")], reactions=True)
    # A вышел из зоны B: (0,0)->(0,-1), B в (0,1): был достан (1), стал вне (2) -> Ao
    assert after.hp["A"] == pytest.approx(20 - 4.5 * t.hit_chance)
    assert after.units["B"].reaction == 0                     # реакция израсходована
    assert after.cells["A"] == (0, -1)


def test_no_ao_on_moving_into_zone():
    sim = Simulation.of(_ctx())
    # AFar: ставим A вне зоны B и заводим внутрь — на ВХОД Ao не положен (только на выход)
    units = {**sim.units, "A": replace(sim.units["A"], cell=(0, -2))}
    after = sim._clone(units).apply_actor_seq("A", [move_action("right")], reactions=True)
    assert after.hp["A"] == 20                                # (0,-2)->(0,-1): вошёл в зону, Ao нет
    assert after.units["B"].reaction == 1


def test_no_ao_when_reaction_spent():
    sim = _sim()
    units = {**sim.units, "B": replace(sim.units["B"], reaction=0)}   # враг без реакции (ranged/потрачена)
    after = sim._clone(units).apply_actor_seq("A", [move_action("left")], reactions=True)
    assert after.hp["A"] == 20                                # выходец из зоны, но реакция 0 -> Ao нет
    assert after.units["B"].reaction == 0


def test_ao_fires_once_across_multiple_leaving_steps():
    # два шага прочь: Ao только на первом (выход из зоны), на втором B уже вне зоны/реакция пуста
    t = tuning()
    after = _sim().apply_actor_seq("A", [move_action("left"), move_action("left")], reactions=True)
    assert after.hp["A"] == pytest.approx(20 - 4.5 * t.hit_chance)   # ровно один Ao
    assert after.cells["A"] == (0, -2)


def test_use_spends_action_and_blocks_second():
    t = tuning()
    # два USE подряд: первый тратит действие и бьёт, второй блокирован (действий не осталось)
    after = _sim().apply_actor_seq("A", [target_action("B"), use_action("sword"),
                                         use_action("sword")], reactions=True)
    assert after.units["A"].action == 0
    assert after.hp["B"] == pytest.approx(20 - 5.5 * t.hit_chance)    # ровно один удар


def test_reactions_false_preserves_v3_semantics():
    t = tuning()
    # v3-путь (reactions=False): действие не тратится, оба USE бьют, Ao нет — бит-в-бит как прежде
    sim = _sim()
    after = sim.apply_actor_seq("A", [target_action("B"), use_action("sword"), use_action("sword")],
                                reactions=False)
    assert after.units["A"].action == 1                       # ресурс не списывался
    assert after.hp["B"] == pytest.approx(20 - 2 * 5.5 * t.hit_chance)
    # движение прочь из зоны без флага реакций — Ao не происходит
    moved = sim.apply_actor_seq("A", [move_action("left")], reactions=False)
    assert moved.hp["A"] == 20
    assert moved.units["B"].reaction == 1


def test_reset_actor_turn_refills_resources():
    sim = _sim()
    spent = sim.apply_actor_seq("A", [target_action("B"), use_action("sword")], reactions=True)
    assert spent.units["A"].action == 0
    fresh = spent.reset_actor_turn("A")
    assert (fresh.units["A"].action, fresh.units["A"].bonus, fresh.units["A"].reaction) == (1, 1, 1)
    # откат только у актёра: потратившая Ao реакция B остаётся 0
    assert fresh.units["B"].reaction == spent.units["B"].reaction
