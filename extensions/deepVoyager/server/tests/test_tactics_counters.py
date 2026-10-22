# tests/test_tactics_counters.py — трасс-агрегат follow_rate/correctness + сборка StepCtx (§11, §7).
#
# Проверяем два уровня: (1) Counters считает применимость по всем шагам, follow_rate=None при
# малом support (не 0%), Wilson CI в [0,1]; (2) build_step_ctx реально извлекает ground-truth
# сигналы из Simulation (не из наблюдения), так что детекторы дают непустой applicable.
import pytest

from arent.tactics import Tag
from arent.tactics_counters import MIN_SUPPORT, Counters, wilson_interval
from arent.tactics_ctx import build_step_ctx
from arent.tactics_detect import detect
from conftest import make_npc, make_scene_payload, make_weapon
from planner.context import BattleContext
from planner.sim import Simulation


def _record(counters, key, applicable=True, fired=False, violated=False):
    counters.record({key} if applicable else set(),
                    {key} if fired else set(),
                    {key} if violated else set())


def test_follow_rate_na_below_min_support():
    counters = Counters()
    for _ in range(MIN_SUPPORT - 1):
        _record(counters, Tag.no_idle.value, applicable=True, fired=True)
    assert counters.follow_rate(Tag.no_idle.value) is None      # N/A, не 0% (§11.3)


def test_follow_rate_ratio_at_support():
    counters = Counters()
    for i in range(MIN_SUPPORT):
        _record(counters, Tag.no_idle.value, applicable=True, fired=(i < 3))
    assert counters.follow_rate(Tag.no_idle.value) == pytest.approx(3 / MIN_SUPPORT)


def test_to_dict_counts_missed_and_gated():
    counters = Counters()
    for _ in range(6):
        _record(counters, Tag.kill_shot.value, applicable=True, fired=True)
    d = counters.to_dict()["tactics"][Tag.kill_shot.value]
    assert d["applicable"] == 6 and d["fired"] == 6 and d["missed"] == 0
    assert d["gated_zero"] is False


def test_wilson_bounds_and_na():
    assert wilson_interval(0, 0) == (None, None)
    lo, hi = wilson_interval(5, 5)
    assert 0.0 <= lo <= 1.0 and 0.0 <= hi <= 1.0 and lo <= hi


# ---------------------------------------------------------------- build_step_ctx из Simulation
def _two_unit_sim():
    hero = make_npc("A", 0, 0, disposition=-1, hp=20, speed=30, damage="1d8")
    foe = make_npc("B", 50, 0, disposition=1, hp=6, speed=0, damage="1d8")
    payload = make_scene_payload(npcs=[hero, foe],
                                 weapons=[make_weapon("sword", damage="1d6+2")], token="B")
    return Simulation.of(BattleContext.from_payload(payload))


def test_build_step_ctx_extracts_ground_truth_signals():
    sim = _two_unit_sim()
    units = sim.units
    hp_max = {uid: u.hp for uid, u in units.items()}
    ctx = build_step_ctx(sim, units, units, sim.hero_id, units[sim.hero_id].cell,
                         target_id="B", attacked=True, round_index=0, hp_max=hp_max)
    assert ctx.actor.role == "melee"                     # роль выведена из hp/reach ground-truth
    assert any(f.id == "B" for f in ctx.foes)
    det = detect(ctx)
    assert det.applicable                                # есть что проверить на этом состоянии
    assert Tag.no_idle.value in det.fired                # атака => не пустоход


def test_build_step_ctx_detects_wounded_killshot_target():
    sim = _two_unit_sim()
    units = sim.units
    # hp_max цели завышен относительно текущего hp => цель ранена (frac < 1)
    hp_max = {uid: (20.0 if uid == sim.hero_id else 10.0) for uid in units}
    ctx = build_step_ctx(sim, units, units, sim.hero_id, units[sim.hero_id].cell,
                         target_id="B", attacked=True, round_index=0, hp_max=hp_max)
    det = detect(ctx)
    assert Tag.focus_wounded.value in det.fired           # единственная досягаемая цель ранена
