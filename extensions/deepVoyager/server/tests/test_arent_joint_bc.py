# tests/test_arent_joint_bc.py — Этап 4: BC-потеря = joint NLL совместной политики.
#
# Проверяем, что behavior cloning обучает РОВНО тот же распределение, что инференс и PPO
# (arent/joint.py + torch_net._joint_batch): отрицательный логарифм демонстрационного действия,
# нормированный по множеству совместно допустимых троек A(s), а не сумма независимых
# cross-entropy. Тесты идут на синтетике с НЕдекартовой legal-маской (реальный joint-эффект),
# без учителя и без полноценного обучения. torch-проверки помечены skipif — на машине без
# torch идут pure-ветки.
import copy
import math
import os
import random

import pytest

from arent import backend, joint, net, paths, train
from arent.backend import available
from arent.pure_net import PurePolicy, _softmax

# Индексы «не атаковать» (последний masked-слот группы) — из единого источника joint.py.
NONE_T = joint.NONE_TARGET
NONE_WEAPON = joint.NONE_WEAPON


def _dims(schema):
    return net.dims_for(schema)


def _pos_key(schema):
    return "plan" if schema == 3 else "cell"


def logsumexp(values):
    if not values:
        return float("-inf")
    top = max(values)
    return top + math.log(sum(math.exp(v - top) for v in values))


def _head_logps(model, sample):
    """Log-softmax каждой головы поверх маскированных слотов: {group: {index: logp}}."""
    *_, logits, _cache, value = model.forward(sample)
    lp = {}
    for group in net.GROUPS:
        allowed, values = logits[group]
        probs = _softmax(values)
        lp[group] = {i: math.log(max(p, 1e-30)) for i, p in zip(allowed, probs)}
    return lp, value


def joint_sample(cfg, seed=1, schema=2, extra=()):
    """Синтетический пример с НЕдекартовым legal и валидной (легальной) меткой учителя.

    extra — доп. тройки (p,t,w), помечаемые допустимыми, чтобы двигать нормировку. Позиции,
    цели и оружие в legal всегда внутри mask==1, поэтому head-logps их покрывают.
    """
    d = _dims(schema)
    rng = random.Random(seed)
    nc, nt, nw = 3, 2, 2
    mc = [1] * nc + [0] * (d["cells"] - nc)
    mt = [1] * nt + [0] * (d["targets"] - nt - 1) + [1]
    mw = [1] * nw + [0] * (d["weapons"] - nw - 1) + [1]
    legal = [[[0 for _ in range(d["weapons"])] for _ in range(d["targets"])]
             for _ in range(d["cells"])]
    for p in range(nc):
        legal[p][NONE_T][NONE_WEAPON] = 1              # канонический «без атаки» на позицию
    legal[0][0][0] = 1
    legal[1][1][0] = 1
    for (p, t, w) in extra:
        legal[p][t][w] = 1
    y = {_pos_key(schema): 0, "target": 0, "weapon": 0}   # тройка (0,0,0) — легальная атака
    return {
        "schema": schema, "state": [rng.uniform(-1, 1) for _ in range(d["state"])],
        "cells": [[rng.uniform(-1, 1) for _ in range(d["cell_feat"])] if i < nc
                  else [0.0] * d["cell_feat"] for i in range(d["cells"])],
        "targets": [[rng.uniform(-1, 1) for _ in range(d["target_feat"])] if i < nt
                    else [0.0] * d["target_feat"] for i in range(d["targets"])],
        "weapons": [[rng.uniform(-1, 1) for _ in range(d["weapon_feat"])] if i < nw
                    else [0.0] * d["weapon_feat"] for i in range(d["weapons"])],
        "mask": {"cells": mc, "targets": mt, "weapons": mw},
        "legal": legal, "y": y, "value": round(rng.uniform(-1, 1), 3),
        "meta": {"arena": "joint_unit", "src": "A", "cell": [0, 0]},
    }


def _reference_total(model, sample):
    """Независимый эталон: joint NLL (logsumexp по A(s)) + value-член 0.5*value_w*diff^2."""
    ip, it, iw = joint.ensure_jointly_legal(sample, sample["schema"])
    lp, value = _head_logps(model, sample)
    Lc, Lt, Lw = lp["cells"], lp["targets"], lp["weapons"]
    legal = sample["legal"]
    us = [Lc[p] + Lt[t] + Lw[w] for p in Lc for t in Lt for w in Lw if legal[p][t][w]]
    logZ = logsumexp(us)
    nll = logZ - (Lc[ip] + Lt[it] + Lw[iw])
    diff = value - float(sample.get("value", 0.0))
    value_part = 0.5 * model.cfg.value_w * diff * diff
    return nll, value_part, nll + value_part


# ------------------------------------------------------------------ случай 1
def test_joint_bc_loss_equals_negative_logprob_of_demo_action():
    """Отчётный BC-loss == (-logπ(a*|s)) + value, т.е. ровно joint NLL демонстрации."""
    cfg = net.Config(hidden=8, head=3, seed=3, schema=2)
    model = PurePolicy(cfg, net.init_params(cfg, _dims(2)))
    sample = joint_sample(cfg, seed=5)
    nll, _value_part, total = _reference_total(model, sample)
    report = model.step_batch([sample], lr=0.0)          # шаг не двигает веса при lr=0
    assert nll > 0.0
    assert report["loss"] == pytest.approx(total, abs=1e-4)


# ------------------------------------------------------------------ случай 2
def test_loss_matches_independent_logsumexp_reference():
    """Два независимых вычисления joint NLL (через step_batch и через эталон) совпадают."""
    cfg = net.Config(hidden=8, head=3, seed=11)
    params = net.init_params(cfg, _dims(2))
    model_a = PurePolicy(cfg, copy.deepcopy(params))
    model_b = PurePolicy(cfg, copy.deepcopy(params))
    sample = joint_sample(cfg, seed=9)
    _nll, _vp, total = _reference_total(model_b, sample)
    report = model_a.step_batch([sample], lr=0.0)
    assert report["loss"] == pytest.approx(total, abs=1e-4)


# ------------------------------------------------------------------ случай 3
def test_illegal_triples_do_not_enter_normalizer():
    """legal==0 на дозволенном слоте исключает тройку из суммы; на pad-слоте — без эффекта."""
    cfg = net.Config(hidden=8, head=3, seed=4)
    params = net.init_params(cfg, _dims(2))
    base = joint_sample(cfg, seed=13)
    pad_index = _dims(2)["cells"] - 1                    # cell-NONE: mask==0, никогда не в A(s)
    assert base["mask"]["cells"][pad_index] == 0

    promoted = copy.deepcopy(base)
    promoted["legal"][2][1][1] = 1                       # был legal==0 на дозволенных слотах
    padset = copy.deepcopy(base)
    padset["legal"][pad_index][0][0] = 1                 # legal==1 на pad-клетке (вне mask)

    l0 = PurePolicy(cfg, copy.deepcopy(params)).step_batch([base], lr=0.0)["loss"]
    l1 = PurePolicy(cfg, copy.deepcopy(params)).step_batch([promoted], lr=0.0)["loss"]
    l2 = PurePolicy(cfg, copy.deepcopy(params)).step_batch([padset], lr=0.0)["loss"]
    assert l0 != pytest.approx(l1, abs=1e-6)             # исключение реально меняло нормировку
    assert l2 == pytest.approx(l0, abs=1e-4)             # pad-тройка массы не получила


# ------------------------------------------------------------------ случай 4
@pytest.mark.skipif("torch" not in available(), reason="torch не установлен")
def test_probabilities_over_admissible_set_sum_to_one():
    """Совместный закон нормирован: Σ_{A(s)} exp(logπ) == 1 (та же реализация, что у PPO)."""
    import torch
    from arent.torch_net import TorchPolicy, _dist, _joint_batch
    cfg = net.Config(hidden=8, head=3, seed=6, device="cpu")
    policy = TorchPolicy(cfg, net.init_params(cfg, _dims(2)), device="cpu")
    sample = joint_sample(cfg, seed=21)
    state, slots, masks = policy._batch([sample])
    with torch.no_grad():
        logits, _v = policy._pass(state, slots, masks)
        head = {g: _dist(logits[g], masks[g])[1] for g in net.GROUPS}
        legal = torch.tensor([sample["legal"]], dtype=torch.float32)
        logpi, _logZ = _joint_batch(head["cells"], head["targets"], head["weapons"], legal)
        probs = logpi.exp() * legal[0]
        assert float(probs.sum().item()) == pytest.approx(1.0, abs=1e-4)


# ------------------------------------------------------------------ случай 5
def test_illegal_teacher_label_raises_diagnostics():
    cfg = net.Config(hidden=8, head=3, seed=2)
    model = PurePolicy(cfg, net.init_params(cfg, _dims(2)))
    sample = joint_sample(cfg, seed=8)
    sample["y"] = {_pos_key(2): 2, "target": 1, "weapon": 1}     # legal[2][1][1] == 0
    with pytest.raises(ValueError, match="вне допустимого множества"):
        model.step_batch([sample], lr=0.0)


def test_noattack_label_is_canonicalized_no_duplicate_probability():
    """Метка «цель без оружия» приводится к канону (поз,NONE,NONE): тот же loss, дубля нет."""
    cfg = net.Config(hidden=8, head=3, seed=2)
    params = net.init_params(cfg, _dims(2))
    aimed = joint_sample(cfg, seed=8)
    aimed["y"] = {_pos_key(2): 1, "target": 0, "weapon": -1}     # legal[1][0][NONE]==0
    canonical = copy.deepcopy(aimed)
    canonical["y"] = {_pos_key(2): 1, "target": -1, "weapon": -1}   # канон (1,NONE,NONE)
    # канонический no-attack для позиции 1 должен быть допустим
    assert aimed["legal"][1][NONE_T][NONE_WEAPON] == 1
    ip, it, iw = joint.ensure_jointly_legal(aimed, 2)
    assert (ip, it, iw) == (1, NONE_T, NONE_WEAPON)          # цель канонизирована в NONE
    l_aim = PurePolicy(cfg, copy.deepcopy(params)).step_batch([aimed], lr=0.0)["loss"]
    l_can = PurePolicy(cfg, copy.deepcopy(params)).step_batch([canonical], lr=0.0)["loss"]
    assert l_aim == pytest.approx(l_can, abs=1e-6)           # одно действие => один loss


def test_illegal_attack_label_raises_despite_weapon_present():
    """Реальная атака (оружие задано), не попадающая в A(s), не канонизируется -> ошибка."""
    cfg = net.Config(hidden=8, head=3, seed=2)
    model = PurePolicy(cfg, net.init_params(cfg, _dims(2)))
    sample = joint_sample(cfg, seed=8)
    sample["y"] = {_pos_key(2): 1, "target": 0, "weapon": 0}     # legal[1][0][0]==0, оружие реально
    with pytest.raises(ValueError, match="вне допустимого множества"):
        model.step_batch([sample], lr=0.0)


def test_missing_joint_mask_raises_diagnostics():
    cfg = net.Config(hidden=8, head=3, seed=2)
    model = PurePolicy(cfg, net.init_params(cfg, _dims(2)))
    sample = joint_sample(cfg, seed=8)
    sample.pop("legal")
    with pytest.raises(ValueError, match="нет совместной маски"):
        model.step_batch([sample], lr=0.0)


# ------------------------------------------------------------------ случай 6
@pytest.mark.parametrize("schema", [2, 3])
def test_valid_labels_schema2_and_schema3(schema):
    cfg = net.Config(hidden=8, head=3, seed=7, schema=schema)
    model = PurePolicy(cfg, net.init_params(cfg, _dims(schema)))
    sample = joint_sample(cfg, seed=17, schema=schema)
    report = model.step_batch([sample], lr=0.05)
    assert math.isfinite(report["loss"]) and report["loss"] > 0.0
    ip, it, iw = joint.ensure_jointly_legal(sample, schema)      # не бросает -> метка в A(s)
    assert sample["legal"][ip][it][iw] == 1


# ------------------------------------------------------------------ случай 7
@pytest.mark.skipif("torch" not in available(), reason="torch не установлен")
def test_gradients_finite_and_differentiable():
    import torch
    from arent.torch_net import TorchPolicy
    cfg = net.Config(hidden=8, head=3, seed=1, device="cpu")
    policy = TorchPolicy(cfg, net.init_params(cfg, _dims(2)), device="cpu")
    samples = [joint_sample(cfg, seed=s) for s in range(4)]
    for _ in range(3):
        report = policy.step_batch(samples, lr=0.1)
        assert math.isfinite(report["loss"])
    for name, param in policy.layers.named_parameters():
        assert param.grad is not None, name
        assert torch.isfinite(param.grad).all(), name


# ------------------------------------------------------------------ случай 8
def test_value_loss_and_old_weights_still_loadable(tmp_path):
    """Value-член живёт, чекпойнт сохраняется/перезагружается, predict и warm-шаг работают."""
    paths.set_workspace(str(tmp_path))
    cfg = net.Config(hidden=8, head=3, seed=5)
    samples = [joint_sample(cfg, seed=s) for s in range(5)]
    report = train.run(name="bcj", samples=samples, val=samples[:2], cfg=cfg, kind="pure",
                       epochs=2, batch=4, log=lambda *_a: None)
    assert os.path.exists(report["checkpoint"])
    again = backend.load_policy(report["checkpoint"], kind="pure")
    out = again.predict(samples[0])
    assert {"cell", "target", "weapon", "value"} <= set(out)
    step = again.step_batch([samples[0]], lr=0.0)
    assert "value" in step and step["value"] >= 0.0


@pytest.mark.skipif("torch" not in available(), reason="torch не установлен")
def test_pure_and_torch_joint_bc_losses_match():
    """Оба бэкенда считают ОДИН joint-закон: их BC-loss совпадают на недекартовой legal."""
    from arent.torch_net import TorchPolicy
    cfg = net.Config(hidden=8, head=3, seed=9)
    params = net.init_params(cfg, _dims(2))
    sample = joint_sample(cfg, seed=23)
    pure = PurePolicy(cfg, copy.deepcopy(params))
    torch_model = TorchPolicy(cfg, copy.deepcopy(params), device="cpu")
    lp = pure.step_batch([sample], lr=0.0)["loss"]
    lt = torch_model.step_batch([sample], lr=0.0)["loss"]
    assert lp == pytest.approx(lt, rel=1e-2, abs=1e-3)
