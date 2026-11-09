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


# --- SCHEMA=5: манёвры (Dash / Disengage / Dodge). Водятся как use фичи-не-атаки. ---

def _with_maneuvers(sim):
    """A умеет три манёвра; item-id вне оружия -> sim различает их по maneuver_kinds."""
    a = replace(sim.units["A"], maneuver_kinds={"dash": "dash", "dis": "disengage", "dodge": "dodge"})
    return sim._clone({**sim.units, "A": a})


def test_dash_spends_action_and_cannot_attack():
    # Рывок: тратит действие, сам удара нет; следующая атака блокирована (действий 0).
    after = _with_maneuvers(_sim()).apply_actor_seq(
        "A", [target_action("B"), use_action("dash"), use_action("sword")], reactions=True)
    assert after.units["A"].action == 0
    assert after.hp["B"] == 20                         # ни рывок, ни заблокированная атака не бьют


def test_dash_move_is_free_of_opportunity_attack_only_when_disengaged():
    # Сам по себе рывок НЕ защищает от Ao: выход из зоны провоцирует (реакция B тратится).
    t = tuning()
    after = _with_maneuvers(_sim()).apply_actor_seq(
        "A", [use_action("dash"), move_action("left")], reactions=True)
    assert after.hp["A"] == pytest.approx(20 - 4.5 * t.hit_chance)
    assert after.units["B"].reaction == 0


def test_disengage_suppresses_opportunity_attack():
    # Отступление: действие списано, флаги подняты, выход из зоны НЕ провоцирует Ao.
    after = _with_maneuvers(_sim()).apply_actor_seq(
        "A", [use_action("dis"), move_action("left")], reactions=True)
    assert after.units["A"].action == 0
    assert after.units["A"].disengaged is True
    assert after.hp["A"] == 20                         # Ao подавлено
    assert after.units["B"].reaction == 1              # реакция врага не израсходована


def test_dodge_halves_incoming_opportunity_attack():
    # Уклонение: Ao против уклоняющегося — с помехой (урон вдвое меньше обычного Ao).
    t = tuning()
    dodged = _with_maneuvers(_sim()).apply_actor_seq(
        "A", [use_action("dodge"), move_action("left")], reactions=True)
    assert dodged.units["A"].dodging is True
    assert dodged.hp["A"] == pytest.approx(20 - 0.5 * 4.5 * t.hit_chance)


def test_dodge_halves_foes_act_damage():
    # Ответ врагов по уклоняющемуся герою: штраф и урон вдвое ниже базового.
    t = tuning()
    base_after, base_pen = _sim().foes_act()                    # B вплотную, бьёт героя
    dodging_state = _with_maneuvers(_sim()).apply_actor_seq("A", [use_action("dodge")], reactions=True)
    dodge_after, dodge_pen = dodging_state.foes_act()
    assert base_pen == pytest.approx(t.damage_penalty * t.hit_chance)
    assert dodge_pen == pytest.approx(0.5 * t.damage_penalty * t.hit_chance)
    assert dodge_after.hp["A"] > base_after.hp["A"]             # уклонение спасает hp


def test_reset_actor_turn_clears_maneuver_flags():
    sim = _with_maneuvers(_sim())
    dodged = sim.apply_actor_seq("A", [use_action("dodge")], reactions=True)
    assert dodged.units["A"].dodging is True
    fresh = dodged.reset_actor_turn("A")
    assert fresh.units["A"].dodging is False and fresh.units["A"].disengaged is False
    assert fresh.units["A"].action == 1


def test_maneuver_ignored_without_reactions_flag():
    # reactions=False (v2/v3) — манёвров нет в обороте; use фичи не меняет hp/флаги как раньше.
    after = _with_maneuvers(_sim()).apply_actor_seq("A", [use_action("dis")], reactions=False)
    assert after.units["A"].action == 1                  # ресурс не списывался (гейт в reactions)
    assert after.units["A"].disengaged is False

