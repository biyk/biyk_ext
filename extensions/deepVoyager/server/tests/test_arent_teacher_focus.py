# tests/test_arent_teacher_focus.py — F-D: усиленный учитель (LOS/укрытие + опасностный
# фокус-огонь), согласованный с F-C, и проверка ценности через НАШУ симуляцию/rollout.
#
# Кратко о проверяемом:
#  • best_strike с предикатом los не выбирает цель без линии видимости (цель за стеной),
#    даже когда она в дистанционной зоне и опаснее остальных;
#  • добивание ценится по угрозе: среди равных по урону целей учитель бьёт опасную
#    (dmg_to_me), а снимая её — снимает и её будущий ответный огонь;
#  • battlecast больше не «бьёт сквозь стену»: выбранная клетка даёт LOS, и план реально
#    наносит урон в симуляции (согласование наблюдения/масок/исполнения/учителя);
#  • на контролируемой сцене план учителя даёт больший rollout, чем альтернативный план
#    (атака безобидного «балласта» вместо добивания угрозы) — метрика симуляции, не бонус.
import copy

from arent.battlecast import BattlecastTeacher
from arent.battlecast_heuristics import Enemy, best_strike
from arent.observe import observe
from conftest import make_npc, make_scene_payload, make_wall, make_weapon
from planner.action import ACTION_TARGET, ACTION_USE
from planner.armament import Weapon
from planner.context import BattleContext
from planner.los import has_los, sight_segments
from planner.points import tuning
from planner.sim import Simulation
from planner.turns import rollout

FH = tuning().hit_chance
_SWORD = Weapon(id="m", name="меч", damage="1d8+2", attack_bonus=3, sure_ft=30, doubt_ft=30)


def test_best_strike_skips_target_without_line_of_sight():
    hidden = Enemy(id="H", cell=(0, 1), hp=1, ac=12, dmg_to_me=99, reach_cells=1, speed_cells=6)
    open_e = Enemy(id="O", cell=(0, 3), hp=1, ac=12, dmg_to_me=1, reach_cells=1, speed_cells=6)
    # без предиката: скрытая цель ближе и опаснее — учитель бы её выбрал
    assert best_strike((0, 0), [hidden, open_e], [_SWORD], FH)[0].id == "H"
    # с los-фильтром (H не видна): выбирается видимая цель, несмотря на меньшую угрозу
    los = lambda a, b: b != (0, 1)                       # noqa: E731
    assert best_strike((0, 0), [hidden, open_e], [_SWORD], FH, los=los)[0].id == "O"


def test_best_strike_focuses_fire_on_the_dangerous_finishable_target():
    safe = Enemy(id="S", cell=(0, 1), hp=1, ac=12, dmg_to_me=1, reach_cells=1, speed_cells=6)
    threat = Enemy(id="T", cell=(0, 2), hp=1, ac=12, dmg_to_me=9, reach_cells=1, speed_cells=6)
    # обе добиваемы; опасная даёт больший EV (добить = снять её ответный огонь) -> бьём её
    assert best_strike((0, 0), [safe, threat], [_SWORD], FH)[0].id == "T"
    # добиваемая угроза важнее «недобиваемого» урона: ev(T) > ev(S)
    _, _, ev_t = best_strike((0, 0), [safe, threat], [_SWORD], FH)
    assert ev_t > tuning().hit_chance * _SWORD.expected_damage


def _wall_ctx(blocked: bool) -> BattleContext:
    """A в (0,0); E в (150,0)->(0,3). Стена x=100 перекрывает LOS из col<=1, но col2 открыт."""
    walls = [make_wall("w", 100, 0, 100, 50, move=0, sight=1)] if blocked else []
    npcs = [make_npc("A", 0, 0, disposition=-1, hp=50, speed=30, initiative=20),
            make_npc("E", 150, 0, disposition=1, hp=30, speed=30, initiative=5)]
    payload = make_scene_payload(walls=walls, npcs=npcs,
                                 weapons=[make_weapon("bow", damage="1d6", sure_ft=100, doubt_ft=100)],
                                 token="E")
    payload.update({"src": "A", "speed": 30})
    return BattleContext.from_payload(payload)


def test_battlecast_never_proposes_a_shot_blocked_by_a_wall():
    teacher = BattlecastTeacher(rounds=1)
    ctx = _wall_ctx(True)
    chosen = teacher.choose(ctx, observe(ctx))
    assert chosen is not None and chosen[5]               # есть атака (strike)
    cell, target = chosen[1], chosen[3]
    seg = sight_segments(ctx)
    assert cell != ctx.src_cell                            # пришлось выглянуть за угол
    assert has_los(ctx, cell, ctx.cell_of(ctx.token(target.id)), seg)   # LOS с позиции атаки


def test_battlecast_stepped_shot_lands_in_simulation():
    teacher = BattlecastTeacher(rounds=1)
    ctx = _wall_ctx(True)
    actions = teacher.plan(ctx)
    used = [a for a in actions if a.action == ACTION_USE]
    assert used, "учитель обязан выбрать атаку (есть клетка с LOS и дальним оружием)"
    after = Simulation.of(ctx).apply_actor("A", actions)
    assert after.units["E"].hp < 30                        # удар из позиции с LOS реально заденет


def test_focus_fire_kill_beats_grazing_filler_on_rollout_scale():
    """Контролируемая сцена: добить опасную цель выгоднее на шкале симуляции, чем
    «почесать» балласт — проверяем выбор учителя и сравниваем с альтернативным планом."""
    npcs = [make_npc("A", 0, 0, disposition=-1, hp=50, speed=30, initiative=20),
            make_npc("F", 50, 0, disposition=1, hp=100, damage="1d4", speed=30, initiative=5,
                     hit_chance=0.65),
            make_npc("T", 100, 0, disposition=1, hp=5, damage="6d6", speed=30, initiative=10,
                     hit_chance=0.65, reach_ft=5)]
    payload = make_scene_payload(npcs=npcs,
                                 weapons=[make_weapon("sw", damage="4d6+2", bonus=5,
                                                      sure_ft=10, doubt_ft=10)], token="T")
    payload.update({"src": "A", "speed": 30})
    ctx = BattleContext.from_payload(payload)
    teacher = BattlecastTeacher(rounds=1)
    plan = teacher.plan(ctx)
    aimed = next(a.conf.get("id") for a in plan if a.action == ACTION_TARGET)
    assert aimed == "T"                                    # учитель добивает угрозу
    alternative = copy.deepcopy(plan)                      # тот же ход, но в балласт
    for a in alternative:
        if a.action == ACTION_TARGET:
            a.conf["id"] = "F"
    assert rollout(ctx, plan, 2) > rollout(ctx, alternative, 2)
