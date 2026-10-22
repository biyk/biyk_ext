# tests/test_shaping_cap.py — инвариант cap: |Σ λ·bonus| за бой ≤ 0.3·|WIN| (§1.2, §7).
#
# Тактический член не должен доминировать исход: сколько бы бонусов ни начислялось за бой,
# кумулятивный shaping обрезается симметрично до cap_of_win·|WIN|. Провераем на синтетике,
# где каждый шаг даёт положительный бонус, и на отрицательной стороне.
import pytest

from arent.tactics import StepCtx, UnitView
from arent.tactics_config import parse
from arent.tactics_shaper import TacticsShaper
from arent.team_reward import WIN

CFG = parse({"weights": {"no_idle": 0.03, "kill_shot": 0.15, "focus_wounded": 0.10},
             "penalties": {"idle_turn": -0.05}, "shaping_cap_of_win": 0.3})


def _attack_ctx():
    foe = UnitView(id="F1", cell=(0, 1), hp=3, hp_max=10, alive=True)
    actor = UnitView(id="me", cell=(0, 0), hp=20, hp_max=20, alive=True)
    return StepCtx(actor=actor, cell_after=(0, 0), foes=(foe,), attacked=True,
                   target_id="F1", strike_range=1.5, dmg_expect=6.0, target_hp_before=3.0)


def _idle_ctx():
    foe = UnitView(id="F1", cell=(0, 5), hp=10, hp_max=10, alive=True)
    actor = UnitView(id="me", cell=(0, 0), hp=20, hp_max=20, alive=True)
    return StepCtx(actor=actor, cell_after=(0, 0), foes=(foe,))


def test_positive_shaping_clamped_to_cap():
    shaper = TacticsShaper(CFG, CFG.allowed())
    shaper.anneal(0, 1)                              # λ=1
    total = 0.0
    for _ in range(30):                              # заведомо больше cap
        total += shaper.addend(_attack_ctx())
    assert abs(shaper.S) <= CFG.cap_of_win * abs(WIN) + 1e-9
    assert total == pytest.approx(shaper.S, abs=1e-6)


def test_negative_shaping_clamped_symmetrically():
    shaper = TacticsShaper(CFG, CFG.allowed())
    shaper.anneal(0, 1)
    for _ in range(30):
        shaper.addend(_idle_ctx())                  # пустоход -> отрицательный штраф
    assert abs(shaper.S) <= CFG.cap_of_win * abs(WIN) + 1e-9


def test_cap_does_not_runaway_beyond_win_fraction():
    shaper = TacticsShaper(CFG, CFG.allowed())
    shaper.anneal(0, 1)
    for _ in range(100):
        shaper.addend(_attack_ctx())
    assert shaper.S == pytest.approx(CFG.cap_of_win * abs(WIN), abs=1e-6)
