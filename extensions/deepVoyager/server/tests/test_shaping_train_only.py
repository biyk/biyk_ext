# tests/test_shaping_train_only.py — shaping только на train; в eval reward == baseline (§1.1, §7).
#
# Ключевой инвариант честного A/B: record_only-шapers (как в team_eval/evaluate) считает
# детекторы и счётчики, но НЕ меняет награду — reward бит-в-бит равен средам без shaper. Иначе
# mean_reward в baseline-сравнении был бы надут тактическими бонусами.
import pytest

from arent.env import FightEnv
from arent.tactics import Penalty, StepCtx, Tag, UnitView
from arent.tactics_config import parse
from arent.tactics_counters import Counters
from arent.tactics_shaper import TacticsShaper
from arent.team_reward import TeamReward
from conftest import make_npc, make_scene_payload, make_weapon

ATTACK = {"cell": 0, "target": 0, "weapon": 0}
NOTHING = {"cell": 0, "target": -1, "weapon": -1}
SEQ = [ATTACK, NOTHING, ATTACK, NOTHING, ATTACK]

CFG = parse({"weights": {"no_idle": 0.03, "kill_shot": 0.15, "focus_wounded": 0.10},
             "penalties": {"idle_turn": -0.05}})


def _scene():
    hero = make_npc("A", 0, 0, disposition=-1, hp=999, speed=30, damage="1d8")
    foe = make_npc("B", 50, 0, disposition=1, hp=999, speed=0, damage="1d8")
    return make_scene_payload(npcs=[hero, foe], weapons=[make_weapon("sword", damage="1d6+2")],
                              token="B")


def _run(shaper):
    env = FightEnv(rounds_cap=8, team=TeamReward())
    if shaper is not None:
        shaper.anneal(0, 1)               # λ=1, чтобы эффект shaping был виден
        env.set_shaper(shaper)
    env.reset(_scene())
    rewards = []
    for label in SEQ:
        _n, r, term, _tr, _info = env.step(label)
        rewards.append(r)
        if term:
            break
    return rewards


def test_record_only_reward_is_bitidentical_to_baseline():
    baseline = _run(None)
    counters = Counters()
    eval_run = _run(TacticsShaper(CFG, CFG.allowed(), counters, record_only=True))
    assert eval_run == baseline                      # shaping не просочился в оценку
    assert counters.steps > 0                        # но счётчики всё равно считает


def test_train_shaper_changes_reward():
    baseline = _run(None)
    train = _run(TacticsShaper(CFG, CFG.allowed(), Counters(), record_only=False))
    assert train != baseline                         # на train тактический член добавляется


def test_arena_gate_blocks_unexpected_bonus():
    """Если no_idle/idle_turn не в allowed арены — bonus_for не начисляет их (§1.4)."""
    counters = Counters()
    allowed = {"focus_wounded", "kill_shot"}          # арена-дуэль без idle-тегов
    env = FightEnv(rounds_cap=8, team=TeamReward())
    shaper = TacticsShaper(CFG, allowed, counters, record_only=False)
    shaper.anneal(0, 1)
    env.set_shaper(shaper)
    env.reset(_scene())
    env.step(NOTHING)                                # пустоход: fired только по idle-тегам
    fired_or_viol = (counters.to_dict()["tactics"]
                     .get("idle_turn", {}).get("violated", 0))
    assert fired_or_viol >= 1                        # детектор увидел anti-паттерн...
    assert shaper.S == pytest.approx(0.0)            # ...но гейт арены не дал наказать


# ------------------------------------------- §Неугасающее ядро: hard мимо λ-затухания и потолка
def _grabbed_archer_ctx():
    archer = UnitView(id="me", cell=(0, 0), hp=10, hp_max=10, alive=True,
                      ranged=True, role="ranged")
    foe = UnitView(id="F1", cell=(0, 1), hp=10, hp_max=10, alive=True, ranged=False)
    return StepCtx(actor=archer, cell_after=(0, 0), foes=(foe,), attacked=True,
                   target_id="F1", in_reach_after=True, strike_range=8.0)


HARD_CFG = parse({"weights": {Tag.kite_max_range.value: 0.15},
                  "penalties": {Penalty.ranged_grabbed.value: -0.5},
                  "hard": [Penalty.ranged_grabbed.value]})


def test_hard_penalty_survives_lambda_decay_to_zero():
    # λ=0 (конец обучения): обычный shaping погас, НО hard-штраф остаётся полным.
    shaper = TacticsShaper(HARD_CFG, HARD_CFG.allowed(), Counters(), record_only=False)
    shaper.anneal(100, 100)                          # decay_linear(100,100)=0 -> λ=0
    assert HARD_CFG.lam(100, 100) == pytest.approx(0.0)
    assert shaper.addend(_grabbed_archer_ctx()) == pytest.approx(-0.5)


def test_hard_penalty_is_capped_not_runaway():
    # §Лечение обвала value (A): hard вне λ, НО под ОБЩИМ потолком. 30 grabbed-шагов при λ=0
    # дают штраф, ограниченный cap_total, а не уходящий в −∞ (иначе value-хед схлопывается).
    shaper = TacticsShaper(HARD_CFG, HARD_CFG.allowed(), Counters(), record_only=False)
    shaper.anneal(100, 100)                          # λ=0: hard всё равно наказывает
    cap = shaper.cap_total                           # 0.3·|WIN| = 1.5
    first = shaper.addend(_grabbed_archer_ctx())
    assert first == pytest.approx(-0.5)              # полный вес (не погас вместе с λ)
    total = first
    for _ in range(30):
        total += shaper.addend(_grabbed_archer_ctx())
    assert abs(shaper.S) <= cap + 1e-9               # накопление под потолком
    assert total == pytest.approx(-cap)              # насыщение на −cap_total, дальше 0


def test_hard_exempt_still_respects_arena_gate():
    # Если hard-тег снят с allowed арены — он не наказывается и как hard (hard ⊂ allowed).
    shaper = TacticsShaper(HARD_CFG, set(), Counters(), record_only=False)
    shaper.anneal(0, 1)
    assert shaper.addend(_grabbed_archer_ctx()) == pytest.approx(0.0)
