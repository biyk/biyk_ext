# tests/test_sim_initiative.py — механика инициативы и командная симуляция (коммит №2).
#
# Инициатива бросается ОДИН раз на живой токен в Simulation.of и держится фиксированной
# через все раунды (как в dnd5e). Источник — поле initiative в payload, иначе честный d20;
# toHit НИКОГДА не служит прокси (в нём смешаны точность и скорость). Детерминизм — от env_seed.
# Заодно: любой живой актёр нашей команды может сходить (apply_actor), а не только герой.
import pytest

from conftest import make_npc, make_scene_payload, make_weapon
from planner.action import move_action, target_action, use_action
from planner.context import BattleContext
from planner.points import tuning
from planner.sim import Simulation

DAMAGE_SWORD = "1d6+2"                 # ожидание 5.5, с hitChance 0.65 -> 3.575


def ctx_of(npcs, weapons=None, speed=30, token="B"):
    payload = {**make_scene_payload(npcs=npcs, weapons=weapons or []), "speed": speed,
               "token": token}
    return BattleContext.from_payload(payload)


def four_units():
    """Герой A + союзник C (наша команда), враги B и D, нейтральный N."""
    return [make_npc("A", 0, 0, disposition=-1, hp=20),
            make_npc("C", 50, 50, disposition=-1, hp=20),
            make_npc("B", 400, 0, disposition=1, hp=20),
            make_npc("D", 400, 50, disposition=1, hp=20),
            make_npc("N", 200, 200, disposition=0, hp=5)]


#--- 1. инициатива детерминирована seed'ом и это перестановка живых -------------
def test_initiative_order_is_a_deterministic_permutation():
    sim = Simulation.of(ctx_of(four_units()), env_seed=7)
    order = sim.initiative_order
    assert sorted(order) == ["A", "B", "C", "D"]     # нейтральный N не воюет
    again = Simulation.of(ctx_of(four_units()), env_seed=7)
    assert again.initiative_order == order           # тот же seed -> тот же порядок


def test_different_seeds_reorder_the_field():
    orders = {Simulation.of(ctx_of(four_units()), env_seed=s).initiative_order
              for s in range(40)}
    assert len(orders) > 1                            # d20 реально перемешивает


def test_explicit_initiative_field_wins_regardless_of_seed():
    npcs = four_units()
    for n in npcs:
        if n["id"] == "D":
            n["initiative"] = 30                     # d20 максимум 20 < 30
    for seed in range(8):
        assert Simulation.of(ctx_of(npcs), env_seed=seed).initiative_order[0] == "D"


#--- 2. источник — initiative, а НЕ toHit --------------------------------------
def test_to_hit_does_not_influence_initiative_order():
    base = four_units()
    boosted = [dict(n, toHit=(99 if n["id"] == "B" else 0)) for n in base]
    left = Simulation.of(ctx_of(base), env_seed=3).initiative_order
    right = Simulation.of(ctx_of(boosted), env_seed=3).initiative_order
    assert left == right                              # одинаковый seed -> порядок тот же


#--- 3. мёртвые выпадают из порядка --------------------------------------------
def test_dead_units_are_absent_from_order_and_living_track():
    npcs = four_units()
    for n in npcs:
        if n["id"] == "B":
            n["hp"] = {"current": 0, "max": 20, "temp": 0}
    sim = Simulation.of(ctx_of(npcs), env_seed=11)
    assert "B" not in sim.initiative_order
    assert list(sim.living_in_order) == [u for u in sim.initiative_order if sim.units[u].is_alive]


def test_next_to_act_walks_the_order_and_skips_dead():
    sim = Simulation.of(ctx_of(four_units()), env_seed=5)
    first = sim.next_to_act()                          # чей ход первым
    assert first == sim.initiative_order[0]
    nxt = sim.next_to_act(first)
    assert nxt in sim.initiative_order and nxt != first


#--- 4. командность: любой актёр нашей команды может сходить --------------------
def test_allies_expose_our_side_but_not_hero_or_neutral():
    sim = Simulation.of(ctx_of(four_units()), env_seed=1)
    assert {a.id for a in sim.allies} == {"C"}         # A — сам герой, N — нейтральный


def test_apply_actor_moves_and_damages_a_foe_without_touching_hero():
    # союзник C вплотную к врагу B: бьёт его, герой A не ходит и не страдает
    npcs = [make_npc("A", 0, 0, disposition=-1, hp=20),
            make_npc("C", 100, 0, disposition=-1, hp=20),
            make_npc("B", 150, 0, disposition=1, hp=20)]
    sim = Simulation.of(ctx_of(npcs, weapons=[make_weapon("sword", damage=DAMAGE_SWORD)]))
    after = sim.apply_actor("C", [target_action("B"), use_action("sword")])
    assert after.hp["B"] == pytest.approx(20 - 5.5 * tuning().hit_chance)
    assert after.hp["A"] == 20                          # герой не затронут


def test_apply_actor_refuses_to_attack_a_friendly():
    # союзник C вплотную к герою A: свой под ударом, но по своему не бьём
    npcs = [make_npc("A", 50, 0, disposition=-1, hp=20),
            make_npc("C", 100, 0, disposition=-1, hp=20),
            make_npc("B", 400, 0, disposition=1, hp=20)]
    sim = Simulation.of(ctx_of(npcs, weapons=[make_weapon("sword", damage=DAMAGE_SWORD)]))
    after = sim.apply_actor("C", [target_action("A"), use_action("sword")])
    assert after.hp["A"] == 20                          # по союзнику не бьём


#--- 5. одиночный контракт advance живёт как прежде (без env_seed) --------------
def test_single_actor_advance_is_unaffected_and_seedless_still_orders():
    ctx = ctx_of(four_units(), weapons=[make_weapon("sword", damage=DAMAGE_SWORD)])
    sim = Simulation.of(ctx)                            # env_seed=None — legacy-вызов
    assert sorted(sim.initiative_order) == ["A", "B", "C", "D"]
    after, _value = sim.advance([target_action("B"), move_action("right")])
    assert after.hero.id == "A"                         # герой остался src
