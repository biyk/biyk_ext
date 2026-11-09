# tests/test_arent_battlecast_maneuvers.py — Этап 4: учитель battlecast выбирает манёвры.
#
# Покрываем:
#  1. Чистые EV-примитивы манёвров (reach_contacts/avoided_opportunities/movement_value).
#  2. Учитель отдаёт use_action(предмет-манёвр) для Dash/Disengage/Dodge, когда манёвр
#     перебивает удар (здесь — явным большим весом тактики).
#  3. serve==train-гейты: нет предметов -> прежний атакующий план (v2/v3/v4 без регресса);
#     нет действия -> манёвр не берётся; сильный удар + нулевые веса -> удар сохраняется.
import pytest

from arent import tactics_config
from arent.battlecast import BattlecastTeacher
from arent.battlecast_heuristics import (Enemy, avoided_opportunities, movement_value,
                                         reach_contacts)
from arent.observe import observe
from arent.tactics_config import ManeuverWeights, TacticsConfig
from conftest import make_npc, make_scene_payload, make_weapon
from planner.action import ACTION_TARGET, ACTION_USE
from planner.context import BattleContext

DASH = {"id": "dash_item", "kind": "dash", "name": "Рывок"}
DISENGAGE = {"id": "disengage_item", "kind": "disengage", "name": "Отступление"}
DODGE = {"id": "dodge_item", "kind": "dodge", "name": "Уклонение"}
ALL_M = [DASH, DISENGAGE, DODGE]


@pytest.fixture(autouse=True)
def _isolate_tactics():
    """Не зависим от боевого points.json: фиксируем тактики на время теста, снимаем после."""
    yield
    tactics_config.set_config(None)


def _pin(**weights):
    kw = {"dash_bonus": 0.0, "disengage_bonus": 0.0, "dodge_bonus": 0.0}
    kw.update(weights)
    tactics_config.set_config(TacticsConfig(enabled_global=True,
                                            maneuver=ManeuverWeights(**kw)))


def _ctx(npcs, weapons, maneuvers=None, speed=30, token="F"):
    p = make_scene_payload(npcs=npcs, weapons=weapons, token=token)
    p.update({"src": "A", "speed": speed})
    if maneuvers is not None:
        p["maneuvers"] = maneuvers
    return BattleContext.from_payload(p)


def _used_item_ids(actions):
    return {a.conf["itemId"] for a in actions if a.action == ACTION_USE}


# ───────────────────────────────────────────────── 1. чистые примитивы
def test_parse_maneuver_weights_from_section():
    cfg = tactics_config.parse({"maneuvers": {"dash_bonus": 2.5, "disengage_bonus": 1.5,
                                              "dodge_bonus": 0.5, "comment": "x"}})
    assert (cfg.maneuver.dash_bonus, cfg.maneuver.disengage_bonus,
            cfg.maneuver.dodge_bonus) == (2.5, 1.5, 0.5)


def test_parse_maneuver_absent_defaults_zero_and_unknown_key_ignored():
    cfg = tactics_config.parse({"maneuvers": {"bogus": 9, "dash_bonus": "не число"}})
    assert cfg.maneuver == ManeuverWeights(0.0, 0.0, 0.0)   # мусор -> default, без падения


def test_reach_contacts_counts_melee_zone():
    e1 = Enemy(id="1", cell=(0, 1), hp=10, ac=12, dmg_to_me=4, reach_cells=1, speed_cells=6)
    e2 = Enemy(id="2", cell=(0, 0), hp=10, ac=12, dmg_to_me=4, reach_cells=1, speed_cells=6)
    e_far = Enemy(id="3", cell=(0, 6), hp=10, ac=12, dmg_to_me=4, reach_cells=1, speed_cells=6)
    assert reach_contacts((0, 0), [e1, e2, e_far]) == 2   # e1,e2 в melee, e_far — нет


def test_avoided_opportunities_sums_leavers_damage():
    e = Enemy(id="1", cell=(0, 1), hp=10, ac=12, dmg_to_me=5, reach_cells=1, speed_cells=6)
    # шаг из melee-зоны (0,0)->(0,4) снимает Ao этого врага; stay (0,0)->(0,1) — не покидает
    assert avoided_opportunities((0, 0), (0, 4), [e]) == pytest.approx(5.0)
    assert avoided_opportunities((0, 0), (0, 0), [e]) == pytest.approx(0.0)


def test_movement_value_dodge_halves_incoming():
    e = Enemy(id="1", cell=(0, 1), hp=10, ac=12, dmg_to_me=8, reach_cells=1, speed_cells=6)
    plain = movement_value((0, 0), (0, 0), [e], dodge=False)
    dodged = movement_value((0, 0), (0, 0), [e], dodge=True)
    # уклонение уменьшает штраф за входящий вдвое -> ценнее на 0.5*dmg
    assert dodged - plain == pytest.approx(0.5 * 8.0)


# ───────────────────────────────────────────────── 2. учитель выбирает манёвр
def test_teacher_picks_dash_when_bonus_high_and_far_enemy():
    a = make_npc("A", 0, 0, disposition=-1, hp=40)
    f = make_npc("F", 4 * 50, 0, disposition=1, hp=40, damage="1d8")   # клетка (0,4)
    ctx = _ctx([a, f], weapons=[], maneuvers=[DASH], speed=10)         # 2 клетки шагом
    _pin(dash_bonus=1000.0)
    actions = BattlecastTeacher().plan(ctx)
    assert _used_item_ids(actions) == {"dash_item"}
    assert not any(x.action == ACTION_TARGET for x in actions)


def test_teacher_picks_disengage_when_bonus_high():
    a = make_npc("A", 0, 0, disposition=-1, hp=40)
    f = make_npc("F", 1 * 50, 0, disposition=1, hp=40, damage="2d6")   # adjacent
    ctx = _ctx([a, f], weapons=[], maneuvers=[DISENGAGE], speed=30)
    _pin(disengage_bonus=1000.0)
    actions = BattlecastTeacher().plan(ctx)
    assert _used_item_ids(actions) == {"disengage_item"}


def test_teacher_picks_dodge_when_bonus_high():
    a = make_npc("A", 0, 0, disposition=-1, hp=40)
    f = make_npc("F", 1 * 50, 0, disposition=1, hp=40, damage="2d6")   # adjacent, входящий есть
    ctx = _ctx([a, f], weapons=[], maneuvers=[DODGE], speed=30)
    _pin(dodge_bonus=1000.0)
    actions = BattlecastTeacher().plan(ctx)
    assert _used_item_ids(actions) == {"dodge_item"}


# ───────────────────────────────────────────────── 3. гейты обратной совместимости
def test_no_maneuver_items_preserves_attack_plan():
    """v2/v3/v4 (maneuver_items пусто): ровно прежний атакующий план, никакого use-манёвра."""
    a = make_npc("A", 0, 0, disposition=-1, hp=40)
    f = make_npc("F", 1 * 50, 0, disposition=1, hp=40, damage="1d8")
    ctx = _ctx([a, f], weapons=[make_weapon("sw", damage="1d8+2", sure_ft=5)],
               maneuvers=None)
    _pin(dash_bonus=1000.0, disengage_bonus=1000.0, dodge_bonus=1000.0)   # даже огромные веса
    actions = BattlecastTeacher().plan(ctx)
    assert _used_item_ids(actions) <= {"sw"}                             # только оружие
    assert any(x.action == ACTION_TARGET for x in actions)


def test_no_maneuver_when_action_unavailable():
    a = make_npc("A", 0, 0, disposition=-1, hp=40)
    f = make_npc("F", 1 * 50, 0, disposition=1, hp=40, damage="2d6")
    ctx = _ctx([a, f], weapons=[make_weapon("sw", damage="1d8+2", sure_ft=5)],
               maneuvers=ALL_M)
    _pin(dodge_bonus=1000.0, disengage_bonus=1000.0, dash_bonus=1000.0)
    obs = observe(ctx)
    obs["me"]["actionRemaining"] = 0.0                                   # действие истрачено
    actions = BattlecastTeacher()._actions(ctx, obs)
    assert _used_item_ids(actions) <= {"sw"}                             # манёвр недоступен


def test_attack_wins_when_strike_strong_and_bonus_zero():
    """Сильный удар (почти добивает) и нулевые веса -> учитель бьёт, а не маневрирует."""
    a = make_npc("A", 0, 0, disposition=-1, hp=40)
    f = make_npc("F", 1 * 50, 0, disposition=1, hp=1, damage="1d4")      # добиваемая цель
    ctx = _ctx([a, f], weapons=[make_weapon("g", damage="5.0", sure_ft=5, bonus=15)],
               maneuvers=ALL_M)
    _pin()                                                               # все веса = 0
    actions = BattlecastTeacher().plan(ctx)
    assert _used_item_ids(actions) == {"g"}
    assert any(x.action == ACTION_TARGET for x in actions)


def test_maneuver_action_decodes_to_label_by_item_id():
    """Выбор манёвра учителем совместим с v5-разметкой: label_of_v5 ловит use-манёвр."""
    from arent import spec, slots_v3
    a = make_npc("A", 0, 0, disposition=-1, hp=40)
    f = make_npc("F", 1 * 50, 0, disposition=1, hp=40, damage="2d6")
    ctx = _ctx([a, f], weapons=[], maneuvers=[DODGE], speed=30)
    _pin(dodge_bonus=1000.0)
    actions = BattlecastTeacher().plan(ctx)
    used = _used_item_ids(actions)
    assert used == {"dodge_item"}
    obs = observe(ctx)
    slots = slots_v3.build(ctx, obs)
    slots.maneuvers = list(ALL_M)
    slots_v3.ensure_plan(slots, ctx, actions)           # вставляем план учителя в слоты
    label = slots_v3.label_of_v5(ctx, slots, actions)
    assert label is not None
    assert label["maneuver"] == ALL_M.index(DODGE)      # dodge -> его индекс в slots.maneuvers
    assert label["target"] == spec.NONE_SLOT
    assert label["weapon"] == spec.NONE_SLOT
