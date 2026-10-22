# tests/test_arent_joint_serving.py — ЭТАП 7 (часть 6): serving пути BC v3 = joint-декодер.
#
# Доказываем контракты, установленные трассировкой этапа 7:
#  • детерминированный выбор политики — максимум СОВМЕСТНОЙ вероятности по A(s)
#    (joint.decode), а не независимый argmax голов + legalize;
#  • когда независимые argmax дают недопустимую тройку, joint-декодер обязан выбрать
#    лучшую ДОПУСТИМУЮ (конструированные логиты — без обучения);
#  • выбор joint-декодера всегда в A(s), а защитный legalize — тождество (на реальных
#    сценах и случайных весах v3);
#  • play.act, evaluate.fight и team_eval.ModelController используют ОДИНlaw (общий
#    joint.decode: равные метки на одном состоянии);
#  • v2-пути не затронуты (нет decoder/joint-полей, baseline не считается);
#  • артефакты этапа 6 не перезаписаны, результаты этапа 7 живут в stage7_out.
import math

import pytest

from arent import (backend, encode_v3, evaluate, joint, legalize as legalize_mod, net, play,
                   polyenv, slots_v3, spec, spec3, team_eval)
from arent.observe import observe
from planner.context import BattleContext
from conftest import make_npc, make_scene_payload, make_weapon

NONE_T = joint.NONE_TARGET
NONE_W = joint.NONE_WEAPON


# --------------------------------------------------------------------------- сцены
def _melee_adjacent():
    a = make_npc("A", 0, 0, disposition=-1, hp=20, initiative=20)
    f = make_npc("F", 1 * 50, 0, disposition=1, hp=20, initiative=5)
    p = make_scene_payload(npcs=[a, f], weapons=[make_weapon("sw", damage="1d8+2", sure_ft=5)])
    p.update({"src": "A", "token": "F", "speed": 30})
    return p


def _melee_far():
    a = make_npc("A", 0, 0, disposition=-1, hp=20, initiative=20)
    f = make_npc("F", 8 * 50, 0, disposition=1, hp=20, initiative=5)
    p = make_scene_payload(npcs=[a, f], weapons=[make_weapon("sw", damage="1d8+2", sure_ft=5)])
    p.update({"src": "A", "token": "F", "speed": 30})
    return p


def _v3_model(seed=5):
    return backend.build(net.Config(schema=3, hidden=16, head=4, seed=seed), kind="pure")


# --------------------------------------------------------------------------- 1. baseline-vs-joint (стенд)
class _StubModel:
    """Модель с КОНСТРУИРУЕМЫМИ log-softmax голов: независимый argmax заведомо вне A(s)."""

    def __init__(self, cells, targets, weapons, value=0.5):
        self.cfg = net.Config(schema=3)
        self._v = (cells, targets, weapons, value)

    def head_logp(self, sample):
        return self._v

    def predict(self, sample):                       # старый serving: argmax каждой головы
        cs, ts, ws, val = self._v
        yk = net.y_key(spec3.SCHEMA)
        return {yk["cells"]: max(range(len(cs)), key=cs.__getitem__),
                yk["targets"]: max(range(len(ts)), key=ts.__getitem__),
                yk["weapons"]: max(range(len(ws)), key=ws.__getitem__),
                "value": val}


def _stub_scene_mask():
    """A(s): канон. no-attack для планов 0 и 1 + РЕАЛЬНАЯ атака (0, t=0, w=0).
    Независимый argmax (план 1, цель 0, оружие 0) — ВНЕ A(s): удар из плана 1 несовместен."""
    totals = joint.group_totals(spec3.SCHEMA)
    pad = -1e30
    cells = [pad] * totals["cells"]
    cells[1], cells[0] = -1.0, -2.0                  # голова клеток сильнее всего любит план 1
    targets = [pad if i > 0 else -3.0 for i in range(totals["targets"])]
    targets[0], targets[NONE_T] = -0.5, -1.5         # цель 0 — любимая голова-цель
    weapons = [pad if i > 0 else -3.0 for i in range(totals["weapons"])]
    weapons[0], weapons[NONE_W] = -0.5, -1.5
    legal = [[[0] * totals["weapons"] for _ in range(totals["targets"])]
             for _ in range(totals["cells"])]
    legal[1][NONE_T][NONE_W] = 1
    legal[0][NONE_T][NONE_W] = 1
    legal[0][0][0] = 1                                # единственный реальный удар — из плана 0
    return cells, targets, weapons, legal


def test_independent_argmax_illegal_but_joint_picks_best_in_As():
    cells, targets, weapons, legal = _stub_scene_mask()
    sample = {"schema": spec3.SCHEMA, "legal": legal}
    model = _StubModel(cells, targets, weapons)

    base = joint.independent_baseline({"cells": cells, "targets": targets, "weapons": weapons},
                                      spec3.SCHEMA)
    assert (base["plan"], base["target"], base["weapon"]) == (1, 0, 0)
    assert not joint.is_jointly_legal(base, legal, spec3.SCHEMA)      # baseline недопустим

    dec = joint.decode(model, sample, schema=spec3.SCHEMA)
    lab = dec["label"]
    assert (lab["plan"], lab["target"], lab["weapon"]) == (0, 0, 0)   # максимум по A(s)
    assert joint.is_jointly_legal(lab, legal, spec3.SCHEMA)
    # тот же результат даёт прямая математика argmax — decode не дублирует её
    assert joint.argmax(legal, cells, targets, weapons, spec3.SCHEMA) == lab

    z = joint.logz(legal, cells, targets, weapons)
    expect = math.exp(cells[0] + targets[0] + weapons[0] - z)
    assert dec["joint_prob"] == pytest.approx(expect, abs=1e-6)
    # нормировка: суммы вероятностей по A(s) == 1
    total = sum(math.exp(cells[p] + targets[t] + weapons[w] - z)
                for p in range(len(legal)) for t in range(len(legal[p]))
                for w in range(len(legal[p][t])) if legal[p][t][w])
    assert total == pytest.approx(1.0, abs=1e-9)


# --------------------------------------------------------------------------- 2. joint всегда легален
@pytest.mark.parametrize("scene", [_melee_far(), _melee_adjacent()])
@pytest.mark.parametrize("seed", [5, 6])
def test_joint_decode_always_legal_and_legalize_identity(scene, seed):
    model = _v3_model(seed)
    e = polyenv.PolyFightEnv(rounds_cap=4, schema=spec3.SCHEMA)
    s = e.reset(scene)
    for _ in range(8):
        dec = joint.decode(model, s, e._ctx, e.slots, spec3.SCHEMA)
        lab = dec["label"]
        assert joint.is_jointly_legal(lab, s["legal"], spec3.SCHEMA)
        # защитный legalize на тех же slots/ctx — ТОЖДЕСТВО (нарушение контракта = ошибка)
        fixed, reason = legalize_mod.legalize(dict(lab), spec3.SCHEMA, e.slots, e._ctx)
        assert reason is None and dict(fixed) == dict(lab)
        s, _r, term, trunc, _i = e.step(dict(lab))
        if term or trunc or s is None:
            break


# --------------------------------------------------------------------------- 3/5. serving-пути = joint
def _v3_sample(payload, model):
    ctx = BattleContext.from_payload(payload)
    obs = observe(ctx)
    slots = slots_v3.build(ctx, obs)
    sample = encode_v3.observation(ctx, obs, slots)
    sample["legal"] = joint.legal_mask(slots, ctx, spec3.SCHEMA)
    return ctx, slots, sample


def test_play_act_uses_joint_decoder_and_no_violation():
    payload = _melee_adjacent()
    model = _v3_model()
    result = play.act(model, payload)
    assert result["decoder"] == "joint_argmax"
    assert result["joint"]["violation"] is False
    ctx, slots, sample = _v3_sample(payload, model)
    dec = joint.decode(model, sample, schema=spec3.SCHEMA)
    assert result["y"] == dec["label"]                       # play.act == общий joint.decode
    assert joint.is_jointly_legal(result["y"], sample["legal"], spec3.SCHEMA)
    # y_proposed — НЕЗАВИСИМЫЙ baseline (диагностика), не исполненное действие
    assert result["y_proposed"] == joint.independent_baseline(dec["logp"], spec3.SCHEMA)


def test_evaluate_fight_zero_policy_violations():
    model = _v3_model()
    row = evaluate.fight(model, _melee_adjacent(), rounds=4)
    assert row["policy_violations"] == 0                    # joint-выбор legalize не чинит


def test_model_controller_shares_joint_semantics():
    payload = _melee_adjacent()
    model = _v3_model()
    e = polyenv.PolyFightEnv(rounds_cap=4, schema=spec3.SCHEMA)
    obs = e.reset(payload)
    ctrl = team_eval.ModelController(model, schema=spec3.SCHEMA)
    lab = ctrl.label(obs, e._ctx, e.slots)
    assert joint.is_jointly_legal(lab, obs["legal"], spec3.SCHEMA)
    assert ctrl.last_baseline is not None                   # baseline-диагностика есть
    # ровно тот же декодер, что зовёт play.act на эквивалентном состоянии
    assert lab == joint.decode(model, obs, e._ctx, e.slots, spec3.SCHEMA)["label"]


def test_fight_teams_separates_baseline_from_policy():
    model = _v3_model()
    row = team_eval.fight_teams(_melee_adjacent(), model, "greedy", rounds_cap=6,
                                schema=spec3.SCHEMA, trace_limit=0)
    # политика (joint) вне A(s) не ходит: счётчик реальных нарушений нулевой
    assert row["cand_policy_outside_As"] == 0
    assert row["cand_corrected"] == 0                       # legalize joint-выбор не правил
    assert row["cand_legalize_calls"] == row["candidate_steps"]   # вызывается на каждый шаг
    # baseline-счётчик независимого argmax отделён и может быть ненулевым
    assert row["cand_baseline_outside_As"] <= row["cand_baseline_steps"]


# --------------------------------------------------------------------------- 6. v2 не затронут
def test_v2_paths_keep_old_semantics():
    payload = _melee_adjacent()
    model = backend.build(net.Config(hidden=8, head=6, seed=5), kind="pure")   # schema 2
    result = play.act(model, payload)
    assert result["schema"] == 2 and "cell" in result["y"]
    assert "decoder" not in result and "joint" not in result    # v2-путь без joint-полей
    e = polyenv.PolyFightEnv(rounds_cap=4, schema=2)
    obs = e.reset(payload)
    ctrl = team_eval.ModelController(model, schema=2)
    lab = ctrl.label(obs, e._ctx, e.slots)
    assert ctrl.last_baseline is None                        # baseline v2 не считается
    out = model.predict(obs)
    assert lab == {k: int(out.get(k, -1)) for k in ctrl.keys}


# --------------------------------------------------------------------------- 7. артефакты этапа 6 цел
def test_stage6_artifacts_preserved_and_stage7_separate():
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))    # server/
    s6 = os.path.join(root, "stage6_out")
    s7 = os.path.join(root, "stage7_out")
    if not os.path.isdir(s6):
        pytest.skip("артефакты этапа 6 отсутствуют в этом окружении")
    for rel in ("stage6_bc.json", "stage6_eval.json",
                os.path.join("runs", "stage6_bc_smoke", "model_best.json"),
                os.path.join("runs", "stage6_bc_smoke", "model.json")):
        assert os.path.exists(os.path.join(s6, rel)), f"потерян артефакт этапа 6: {rel}"
    # файлы этапа 7 живут ТОЛЬКО в stage7_out и не пересекаются с именами этапа 6
    if os.path.isdir(s7):
        s6_names = {f for f in os.listdir(s6) if os.path.isfile(os.path.join(s6, f))}
        s7_names = {f for f in os.listdir(s7) if os.path.isfile(os.path.join(s7, f))}
        assert not (s6_names & s7_names), "этап 7 перезаписал файлы этапа 6"
