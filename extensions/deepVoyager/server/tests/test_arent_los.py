# tests/test_arent_los.py — F-C: единый механизм линии видимости (LOS).
#
# Наблюдение (observe), маски (slots/slots_v3) и исполнение урона (planner/sim) теперь
# используют ОДНО правило (planner/los): удар проходит, только если цель в дистанции И
# из ПОЗИЦИИ АТАКИ есть прямая без стен с флагом sight. Регрессия закрывает проёмы:
#   • выстрел на открытом пространстве проходит;
#   • выстрел сквозь стену — нет (раньше урон проходил, т.к. sim смотрел только дистанцию);
#   • лучник за укрытием не получает ответа (foes_act перепроверяет LOS по новой клетке);
#   • «выйти из-за угла — выстрелить — вернуться» легально (LOS по attack_cell, не end_cell);
#   • маска (attackable / attackable_v3) отвергает цель в дистанции, но без LOS.
from arent.observe import observe
from arent.slots import Slots, attackable
from arent.slots_v3 import SlotsV3, attackable_v3
from conftest import make_npc, make_scene_payload, make_wall, make_weapon
from planner.action import move_action, target_action, use_action
from planner.context import BattleContext
from planner.los import has_los, los_clear, sight_segments, striking_distance
from planner.sim import Simulation

# Координаты (сетка 50фт): A в (0,0); стена вертикально x=50 между col0 и col1.
# B в (150,0) -> клетка (0,3): из (0,0) в него стрелять нельзя (перекрыто x=50),
# из (0,1) [центр 75] — можно (прямая 75..175 не задевает x=50).
_BOW = make_weapon("bow", "лук", damage="1d6", sure_ft=5, doubt_ft=100)


def _wall():
    return make_wall("w", 50, 0, 50, 50, move=0, sight=1)     # мешает обзору, не ходьбе


def _ranged_ctx(blocked: bool) -> BattleContext:
    npcs = [make_npc("A", 0, 0, disposition=-1, hp=30), make_npc("B", 150, 0, disposition=1, hp=30)]
    payload = make_scene_payload(walls=[_wall()] if blocked else [], npcs=npcs, weapons=[_BOW],
                                 token="B")
    payload.update({"src": "A", "speed": 30})
    return BattleContext.from_payload(payload)


def _melee_ctx(blocked: bool) -> BattleContext:
    """A в (0,0), ближний враг F в (0,1); стена x=50 между ними лишает F линии видимости."""
    npcs = [make_npc("A", 0, 0, disposition=-1, hp=30),
            make_npc("F", 50, 0, disposition=1, hp=30, speed=0)]
    payload = make_scene_payload(walls=[_wall()] if blocked else [], npcs=npcs, weapons=[],
                                 token="F")
    payload.update({"src": "A"})
    return BattleContext.from_payload(payload)


def test_los_primitives_open_vs_wall():
    clear, blocked = _ranged_ctx(False), _ranged_ctx(True)
    assert los_clear(clear, (0, 0), (0, 3)) is True
    assert los_clear(blocked, (0, 0), (0, 3)) is False      # стена x=50 поперёк прямой
    assert los_clear(blocked, (0, 1), (0, 3)) is True       # выглянул — видно
    seg = sight_segments(blocked)
    assert has_los(blocked, (0, 0), (0, 3), seg) is False
    # striking_distance: дистанция есть, но без LOS удар недоступен
    assert striking_distance(blocked, (0, 0), (0, 3), 20.0) is False
    assert striking_distance(blocked, (0, 1), (0, 3), 20.0) is True


def test_apply_actor_wall_blocks_damage_open_hits():
    hit = [target_action("B"), use_action("bow")]
    blocked = Simulation.of(_ranged_ctx(True)).apply_actor("A", hit)
    assert blocked.units["B"].hp == 30                     # сквозь стену урона нет
    open_shot = Simulation.of(_ranged_ctx(False)).apply_actor("A", hit)
    assert open_shot.units["B"].hp < 30                    # на открытом — задет


def test_apply_actor_seq_uses_attack_position_not_end():
    # «выглянул (вправо) — выстрелил — вернулся (влево)»: урон по attack_cell (0,1),
    # хотя финальная клетка снова за стеной.
    step_out = [target_action("B"), move_action("right"), use_action("bow"), move_action("left")]
    after = Simulation.of(_ranged_ctx(True)).apply_actor_seq("A", step_out)
    assert after.units["B"].hp < 30                        # выстрел с позиции атаки прошёл
    assert after.cells["A"] == (0, 0)                       # вернулся за укрытие
    # остаётся за стеной (attack_cell == (0,0)) — выстрела нет, даже когда цель в дистанции
    stay = [target_action("B"), use_action("bow")]
    assert Simulation.of(_ranged_ctx(True)).apply_actor_seq("A", stay).units["B"].hp == 30


def test_foes_act_cover_protects_and_rechecks_new_position():
    # враг в упор, но за стеной: ответа нет (покрытие защищает);
    hurt, penalty = Simulation.of(_melee_ctx(True)).foes_act()
    assert hurt.units["A"].hp == 30
    # то же без стены: враг с ближайшей клетки бьёт (LOS перепроверяется по клетке героя)
    open_foe, _ = Simulation.of(_melee_ctx(False)).foes_act()
    assert open_foe.units["A"].hp < 30


def test_masks_reject_within_range_without_los():
    ctx = _ranged_ctx(True)
    targets, weapons = [{"id": "B", "alive": True}], [{"doubtCells": 20.0}]
    v3 = SlotsV3(plans=[{"attack_cell": (0, 0)}, {"attack_cell": (0, 1)}],
                 targets=targets, weapons=weapons)
    assert attackable_v3(v3, ctx, 0, 0, 0) is False         # из-за стены — маска снимает атаку
    assert attackable_v3(v3, ctx, 1, 0, 0) is True          # с позиции атаки видно
    v2 = Slots(cells=[{"cell": (0, 0)}, {"cell": (0, 1)}], targets=targets, weapons=weapons)
    assert attackable(v2, ctx, 0, 0, 0) is False
    assert attackable(v2, ctx, 1, 0, 0) is True


def test_observation_los_matches_execution_rule():
    # «что видно» (observe) и «что заденет» (striking_distance) — одно и то же: LOS-флаг цели
    # совпадает с тем, разрешит ли маску/исполнение удар из той же клетки.
    for blocked in (True, False):
        ctx = _ranged_ctx(blocked)
        enemy = next(e for e in observe(ctx)["enemies"] if e["id"] == "B")
        assert enemy["los"] is not blocked
        assert striking_distance(ctx, (0, 0), (0, 3), 20.0) is (not blocked)
