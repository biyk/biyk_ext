# tests/test_shaping_diagnostics.py — разложение награды шага для поиска вредных наград.
#
# Цель диагностики: увидеть в трейсе, КАКУЮ награду получает модель за каждое действие —
# и поймать reward-hacking, когда ПЛОХОЕ поведение (не бьёт / подставляется) получает +шанс.
# Для этого шейпер на каждом шаге обязан сохранять as-if-разбор (fired/violated + веса), НЕ
# меняя саму награду. record_only по-прежнему возвращает 0 (§1.1 — reward честный).
import pytest

from arent.env import FightEnv
from arent.tactics import StepCtx, UnitView
from arent.tactics_config import parse
from arent.tactics_counters import Counters
from arent.tactics_shaper import TacticsShaper
from arent.team_reward import TeamReward
from conftest import make_npc, make_scene_payload, make_weapon

CFG = parse({"weights": {"no_idle": 0.03, "kill_shot": 0.15, "focus_wounded": 0.10},
             "penalties": {"idle_turn": -0.05}})
ATTACK = {"cell": 0, "target": 0, "weapon": 0}


def _attack_ctx():
    # один удар по единственному раненому врагу, урон добивает -> no_idle + kill_shot + focus_wounded.
    foe = UnitView(id="F1", cell=(0, 1), hp=3, hp_max=10, alive=True)
    actor = UnitView(id="me", cell=(0, 0), hp=20, hp_max=20, alive=True)
    return StepCtx(actor=actor, cell_after=(0, 0), foes=(foe,), attacked=True,
                   target_id="F1", strike_range=1.5, dmg_expect=6.0, target_hp_before=3.0)


# ------------------------------------------------------------------ шейпер: as-if диагностика без утечки в награду
def test_record_only_stashes_diag_but_returns_zero():
    shaper = TacticsShaper(CFG, CFG.allowed(), Counters(), record_only=True)
    shaper.anneal(0, 1)                              # λ=1
    assert shaper.addend(_attack_ctx()) == 0.0       # в награду record_only НЕ течёт
    d = shaper.last_diag
    assert set(d["fired"]) >= {"no_idle", "kill_shot", "focus_wounded"}
    assert d["weights"]["kill_shot"] == pytest.approx(0.15)
    assert d["asif"] == pytest.approx(0.28, abs=1e-6)   # 0.03+0.15+0.10 — сколько ДАЛО БЫ на train


def test_train_diag_asif_equals_addend_under_cap():
    shaper = TacticsShaper(CFG, CFG.allowed(), Counters(), record_only=False)
    shaper.anneal(0, 1)
    add = shaper.addend(_attack_ctx())
    assert shaper.last_diag["asif"] == pytest.approx(add, abs=1e-6)   # до cap asif == начислено


# ------------------------------------------------------------------ среда: разложение награды в info
def test_env_step_reports_reward_breakdown():
    hero = make_npc("A", 0, 0, disposition=-1, hp=999, speed=30, damage="1d8")
    foe = make_npc("B", 50, 0, disposition=1, hp=999, speed=0, damage="1d8")
    payload = make_scene_payload(npcs=[hero, foe],
                                 weapons=[make_weapon("sword", damage="1d6+2")], token="B")
    env = FightEnv(rounds_cap=8, team=TeamReward())
    env.reset(payload)
    _n, r, _term, _tr, info = env.step(ATTACK)
    rb = info["reward_breakdown"]
    assert set(rb) >= {"base", "potential", "tactical_applied", "outcome"}
    assert rb["tactical_applied"] == pytest.approx(0.0)          # shaper не пристёгнут
    assert rb["base"] + rb["potential"] + rb["tactical_applied"] == pytest.approx(r, abs=1e-4)
