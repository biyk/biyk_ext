# tests/test_tactics_detect.py — детекторы тактик на синтетических StepCtx (§2.2, §7).
#
# Каждый тег проверяется в паре «совпал / не совпал», плюс штрафы как violated, и bonus_for
# считает сумму строго по разрешённым на арене ключам (arena-gate, §1.4). Никакого env:
# чистые данные, чтобы логику детектора можно было исчерпать без симуляции.
import pytest

from arent.tactics import Penalty, StepCtx, Tag, UnitView
from arent.tactics_detect import bonus_for, detect

# допуск: расстояние «вплотную» = соседняя клетка с диагональным допуском движка
TOL = 0.6


def unit(uid, cell, hp=10, hp_max=10, alive=True, reach=1.0, speed=6, dmg=5.0,
         chance=0.65, ranged=False, role="melee", los=True):
    return UnitView(id=uid, cell=cell, hp=hp, hp_max=hp_max, alive=alive, reach=reach,
                    speed=speed, dmg=dmg, chance=chance, ranged=ranged, role=role, los=los)


def melee_actor(cell=(0, 0), hp=20, ranged=False, speed=6, role="melee"):
    return unit("me", cell, hp=hp, hp_max=20, speed=speed, ranged=ranged, role=role)


def ctx(**kw):
    base = dict(actor=kw.pop("actor", None) or melee_actor(), cell_after=(0, 0))
    base.update(kw)
    return StepCtx(**base)


def fired_keys(c):
    return {k for k in detect(c).fired}


def violated_keys(c):
    return {k for k in detect(c).violated}


# --------------------------------------------------------------------------- no_idle / idle_turn
def test_no_idle_fires_on_attack():
    foe = unit("F1", (0, 1))
    c = ctx(foes=(foe,), attacked=True, target_id="F1", strike_range=1.5)
    assert Tag.no_idle.value in fired_keys(c)
    assert Penalty.idle_turn.value not in violated_keys(c)


def test_idle_turn_penalizes_wasted_turn():
    foe = unit("F1", (0, 5))
    c = ctx(foes=(foe,), attacked=False, moved=False, cell_after=(0, 0))
    assert Penalty.idle_turn.value in violated_keys(c)


def test_moving_closer_without_attack_earns_no_idle():
    # §Переразметка: no_idle больше НЕ платит за ход без атаки. Сближение-без-выстрела —
    # нейтрально (ни бонуса, ни штрафа): морковка теперь строго за ДЕЙСТВИЕ, ведущее к победе.
    foe = unit("F1", (0, 5))
    c = ctx(actor=melee_actor((0, 0)), foes=(foe,), moved=True, cell_after=(0, 4))
    assert Tag.no_idle.value not in fired_keys(c)
    assert Penalty.idle_turn.value not in violated_keys(c)


# --------------------------------------------------------------------------- focus_wounded / kill_shot
def test_focus_wounded_hits_lowest_hp_reachable():
    wounded = unit("F1", (0, 1), hp=3, hp_max=10)
    healthy = unit("F2", (1, 1), hp=10, hp_max=10)
    c = ctx(foes=(wounded, healthy), attacked=True, target_id="F1",
            target_hp_before=3, strike_range=1.5)
    assert Tag.focus_wounded.value in fired_keys(c)


def test_focus_wounded_not_fire_on_healthy_when_wounded_available():
    wounded = unit("F1", (0, 1), hp=3, hp_max=10)
    healthy = unit("F2", (1, 1), hp=10, hp_max=10)
    c = ctx(foes=(wounded, healthy), attacked=True, target_id="F2",
            target_hp_before=10, strike_range=1.5)
    assert Tag.focus_wounded.value not in fired_keys(c)


def test_kill_shot_fires_when_damage_finishes_target():
    foe = unit("F1", (0, 1), hp=4, hp_max=10)
    c = ctx(foes=(foe,), attacked=True, target_id="F1", target_hp_before=4,
            dmg_expect=6.5, strike_range=1.5)
    assert Tag.kill_shot.value in fired_keys(c)


def test_kill_shot_not_fire_when_target_survives():
    foe = unit("F1", (0, 1), hp=20, hp_max=30)
    c = ctx(foes=(foe,), attacked=True, target_id="F1", target_hp_before=20,
            dmg_expect=5.0, strike_range=1.5)
    assert Tag.kill_shot.value not in fired_keys(c)


# --------------------------------------------------------------------------- kite / approach penalty
def test_kite_max_range_back_off_and_shoot():
    archer = melee_actor((0, 0), ranged=True, role="ranged")
    melee_foe = unit("F1", (0, 3), speed=6)
    c = ctx(actor=archer, foes=(melee_foe,), cell_after=(0, -4), moved=True,
            attacked=True, target_id="F1", strike_range=8.0)
    assert Tag.kite_max_range.value in fired_keys(c)


def test_kite_max_range_fires_on_single_cell_retreat():
    # §Дисциплина дистанции: порог расслаблен — достаточно отойти хотя бы на клетку и
    # выстрелить. Раньше требовался шаг >= speed/2 (для speed=6 — 3 клетки), что на тесной
    # аренде недостижимо: kite_max_range имел 334 applicable и 0 fired.
    archer = melee_actor((0, 0), ranged=True, role="ranged", speed=6)
    melee_foe = unit("F1", (0, 4), speed=6)
    c = ctx(actor=archer, foes=(melee_foe,), cell_after=(0, -1), moved=True,
            attacked=True, target_id="F1", strike_range=8.0)
    assert Tag.kite_max_range.value in fired_keys(c)


def test_kite_max_range_not_fire_when_not_attacking():
    archer = melee_actor((0, 0), ranged=True, role="ranged", speed=6)
    melee_foe = unit("F1", (0, 4), speed=6)
    c = ctx(actor=archer, foes=(melee_foe,), cell_after=(0, -1), moved=True,
            attacked=False, strike_range=8.0)
    assert Tag.kite_max_range.value not in fired_keys(c)


def test_approach_milishnik_as_archer_penalized():
    archer = melee_actor((0, 0), ranged=True, role="ranged")
    melee_foe = unit("F1", (0, 8), speed=6)
    c = ctx(actor=archer, foes=(melee_foe,), cell_after=(0, 4), moved=True)
    assert Penalty.approach_milishnik_as_archer.value in violated_keys(c)


# --------------------------------------------------------------------------- cover_shoot / shoot_from_open
def test_cover_shoot_fires_when_behind_cover():
    archer = melee_actor((0, 0), ranged=True, role="ranged")
    foe = unit("F1", (0, 5))
    c = ctx(actor=archer, foes=(foe,), attacked=True, target_id="F1", cover_after=True,
            strike_range=8.0)
    assert Tag.cover_shoot.value in fired_keys(c)


def test_shoot_from_open_penalized():
    archer = melee_actor((0, 0), ranged=True, role="ranged")
    foe = unit("F1", (0, 5))
    c = ctx(actor=archer, foes=(foe,), attacked=True, target_id="F1", cover_after=False,
            strike_range=8.0)
    assert Penalty.shoot_from_open.value in violated_keys(c)


# --------------------------------------------------------------------------- stand_off_shoot
def test_stand_off_shoot_fires_when_ranged_attacks_from_out_of_reach():
    # §Дисциплина дистанции: главный бонус для дальнобойного — стрелять, оставаясь вне
    # melee-зоны врага. На Этапе 3 укрытий нет, поэтому именно stand_off (а не cover_shoot)
    # должен вести политику; раньше такой морковки не существовало вовсе.
    archer = melee_actor((0, 0), ranged=True, role="ranged")
    foe = unit("F1", (0, 5))
    c = ctx(actor=archer, foes=(foe,), attacked=True, target_id="F1",
            in_reach_after=False, strike_range=8.0)
    assert Tag.stand_off_shoot.value in fired_keys(c)


def test_stand_off_shoot_not_fire_when_stood_in_enemy_reach():
    archer = melee_actor((0, 0), ranged=True, role="ranged")
    foe = unit("F1", (0, 1))
    c = ctx(actor=archer, foes=(foe,), attacked=True, target_id="F1",
            in_reach_after=True, strike_range=8.0)
    assert Tag.stand_off_shoot.value not in fired_keys(c)


def test_stand_off_shoot_not_applicable_without_attack():
    archer = melee_actor((0, 0), ranged=True, role="ranged")
    foe = unit("F1", (0, 5))
    c = ctx(actor=archer, foes=(foe,), attacked=False, moved=False,
            in_reach_after=False, strike_range=8.0)
    assert Tag.stand_off_shoot.value not in fired_keys(c)


# --------------------------------------------------------------------------- reach
def test_enter_reach_penalized_when_damaged():
    spear = unit("F1", (0, 2), reach=2.0)
    c = ctx(foes=(spear,), moved=True, cell_after=(0, 1), in_reach_after=True,
            took_damage=True)
    assert Penalty.enter_reach.value in violated_keys(c)


def test_avoid_reach_fires_when_stayed_out():
    spear = unit("F1", (0, 4), reach=2.0)
    c = ctx(foes=(spear,), moved=True, cell_after=(0, 3), in_reach_after=False)
    assert Tag.avoid_reach.value in fired_keys(c)


# --------------------------------------------------------------------------- focus_fire / spread_fire
def test_focus_fire_when_teammate_already_hit_same_target():
    foe = unit("F1", (0, 1))
    ally = unit("A1", (-1, 0))
    c = ctx(foes=(foe,), allies=(ally,), attacked=True, target_id="F1",
            prior_allies_on_target=1, strike_range=1.5)
    assert Tag.focus_fire.value in fired_keys(c)


def test_spread_fire_penalized_when_teammates_hit_other_target():
    f1, f2 = unit("F1", (0, 1)), unit("F2", (1, 1))
    ally = unit("A1", (-1, 0))
    c = ctx(foes=(f1, f2), allies=(ally,), attacked=True, target_id="F2",
            prior_allies_on_target=0, prior_ally_targets=("F1",), strike_range=1.5)
    assert Penalty.spread_fire.value in violated_keys(c)


# --------------------------------------------------------------------------- priority_soft / boss
def test_priority_soft_hits_archer_not_tank():
    tank = unit("F1", (0, 1), role="tank", hp=40, hp_max=40)
    archer = unit("F2", (1, 1), role="ranged", ranged=True, hp=8, hp_max=8)
    c = ctx(foes=(tank, archer), attacked=True, target_id="F2", strike_range=2.0,
            target_hp_before=8)
    assert Tag.priority_soft.value in fired_keys(c)


def test_hit_boss_with_adds_penalized():
    boss = unit("F1", (0, 1), role="tank", hp=40, hp_max=40)
    add = unit("F2", (1, 1), role="melee", hp=6, hp_max=6)
    c = ctx(foes=(boss, add), attacked=True, target_id="F1", strike_range=2.0,
            target_hp_before=40)
    assert Penalty.hit_boss_with_adds.value in violated_keys(c)


# --------------------------------------------------------------------------- ring / contacts
def test_break_ring_fires_when_contacts_drop():
    foes = (unit("F1", (0, 1)), unit("F2", (1, 0)))
    c = ctx(foes=foes, moved=True, cell_after=(0, 4), contacts_before=2, contacts_after=1)
    assert Tag.break_ring.value in fired_keys(c)


# --------------------------------------------------------------------------- stack
def test_stack_close_penalized_when_ally_adjacent():
    ally = unit("A1", (0, 1))
    c = ctx(allies=(ally,), cell_after=(0, 0), moved=True)
    assert Penalty.stack_close.value in violated_keys(c)


def test_no_stack_fires_when_allies_spread():
    ally = unit("A1", (0, 4))
    c = ctx(allies=(ally,), cell_after=(0, 0), moved=True)
    assert Tag.no_stack.value in fired_keys(c)


# --------------------------------------------------------------------------- low hp
def test_melee_at_low_hp_penalized():
    actor = melee_actor((0, 0), hp=5)          # 5/20 = 0.25 < 0.30
    foe = unit("F1", (0, 1))
    c = ctx(actor=actor, foes=(foe,), cell_after=(0, 1), contacts_after=1)
    assert Penalty.melee_at_low_hp.value in violated_keys(c)


def test_retreat_low_hp_fires_when_fleeing():
    actor = melee_actor((0, 0), hp=5)
    foe = unit("F1", (0, 2))
    c = ctx(actor=actor, foes=(foe,), moved=True, cell_after=(0, 6), contacts_after=0)
    assert Tag.retreat_low_hp.value in fired_keys(c)


def test_retreat_low_hp_fires_even_with_contacts():
    # §Дисциплина дистанции: убрано требование contacts_after==0. На тесной арене
    # дальнобойный почти никогда полностью не сбрасывает контакт, поэтому прежний порог
    # давал retreat_low_hp 277 applicable и 0 fired. Растянуть дистанцию = уже отход.
    actor = melee_actor((0, 0), hp=5)
    foe = unit("F1", (0, 2))
    c = ctx(actor=actor, foes=(foe,), moved=True, cell_after=(0, -1), contacts_after=1)
    assert Tag.retreat_low_hp.value in fired_keys(c)


# --------------------------------------------------------------------------- bonus_for / arena-gate
def test_bonus_for_sums_only_allowed_keys():
    foe = unit("F1", (0, 1), hp=3, hp_max=10)
    c = ctx(foes=(foe,), attacked=True, target_id="F1", target_hp_before=3,
            dmg_expect=6.5, strike_range=1.5)
    weights = {Tag.focus_wounded.value: 0.10, Tag.kill_shot.value: 0.15}
    d_full = detect(c)
    assert bonus_for(d_full, allowed=None, weights=weights, penalties={}) == pytest.approx(0.25)
    # arena-gate: если kill_shot не ожидается — его бонус не начисляется
    assert bonus_for(d_full, allowed={Tag.focus_wounded.value}, weights=weights,
                     penalties={}) == pytest.approx(0.10)


def test_bonus_for_applies_penalty_weights():
    foe = unit("F1", (0, 5))
    c = ctx(foes=(foe,))                          # пустоход -> idle_turn
    penalties = {Penalty.idle_turn.value: -0.05}
    assert bonus_for(detect(c), allowed=None, weights={}, penalties=penalties) == pytest.approx(-0.05)


def test_bonus_for_rejects_unknown_key():
    d = detect(ctx(foes=(unit("F1", (0, 1), hp=3, hp_max=10),), attacked=True,
                   target_id="F1", strike_range=1.5))
    with pytest.raises(KeyError):
        bonus_for(d, allowed=None, weights={"not_a_real_tag": 1.0}, penalties={})
