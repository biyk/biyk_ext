# tests/test_arent_joint_selection.py — ЭТАП 8 (часть 4): метрики и отбор по joint-политике.
#
# Доказываем:
#  • joint NLL нормирован по A(s) (на декартовой маске он совпал бы с суммой независимых
#    CE; на вырезанной комбинации — расходится: нормировка активна);
#  • joint_decode_accuracy считает ровно тот же joint.argmax/joint.decode, что serving;
#  • независимая accuracy может ОТЛИЧАТЬСЯ от joint decode accuracy и не подменяет её
#    (стенд: joint-выбор правильный при неверном независимом argmax -> 1.0 против 0.0);
#  • epoch loss — среднее по ВСЕМ батчам с весом по размеру: не зависит от разбиения
#    (lr=0 веса не трогает, сравним побатчевые прогоны с целиком);
#  • model_best.json = эпоха с МИНИМУМОМ val.joint_nll (может не совпадать с последней,
#    даже когда независимая accuracy на последней выше); без joint_nll отбор отказывается;
#  • schema v2 не регрессирует: обучение с новыми метриками проходит, crit = val.joint_nll.
import copy
import json
import math

import pytest

from arent import joint, net, paths, scores, spec, train
from arent.backend import build
from arent.pure_net import PurePolicy
from test_arent_net import _cartesian_legal, fake_samples, spec_dims


def _entries(legal):
    for p, row in enumerate(legal):
        for t, col in enumerate(row):
            for w, val in enumerate(col):
                if val:
                    yield p, t, w


@pytest.fixture
def cfg():
    return net.Config(hidden=16, head=4, seed=3)


@pytest.fixture
def samples():
    return fake_samples(6)


# ------------------------------------------------------------------ 1. joint NLL по A(s)
def test_joint_nll_is_normalized_over_A_s():
    cfg = net.Config(hidden=8, head=3, seed=2)
    model = build(cfg, kind="pure")
    s = fake_samples(2, seed=4)[0]
    ip, it, iw = joint.ensure_jointly_legal(s, net.SCHEMA)
    legal = copy.deepcopy(s["legal"])
    victim = next(p for p in range(len(legal))
                  if p != ip and any(any(c) for c in legal[p]))
    legal[victim][joint.NONE_TARGET][joint.NONE_WEAPON] = 0        # неканонический вырез
    s2 = dict(s, legal=legal)

    lcs, lts, lws, _v = model.head_logp(s2)
    us = [lcs[p] + lts[t] + lws[w] for p, t, w in _entries(legal)]
    top = max(us)
    logZ = top + math.log(sum(math.exp(u - top) for u in us))
    expect = logZ - (lcs[ip] + lts[it] + lws[iw])
    assert scores.sample_joint_nll(model, s2) == pytest.approx(expect, abs=1e-9)
    # нормировка по A(s) активна: joint NLL отличается от суммы независимых голов CE
    indep = -lcs[ip] - lts[it] - lws[iw]
    assert abs(expect - indep) > 1e-4
    # метрика по набору = среднее тех же поэлементных значений
    m = scores.metrics(model, [s, s2])
    both = (scores.sample_joint_nll(model, s) + scores.sample_joint_nll(model, s2)) / 2
    assert m["joint_nll"] == pytest.approx(both, abs=1e-5)
    assert m["n_joint"] == 2


# ------------------------------------------------------------------ 2. decode accuracy == serving
def test_joint_decode_accuracy_matches_joint_decode():
    cfg = net.Config(hidden=8, head=3, seed=3)
    model = build(cfg, kind="pure")
    samples = fake_samples(4, seed=5)
    yk = net.y_key(net.SCHEMA)
    hits = 0
    for s in samples:
        ip, it, iw = joint.ensure_jointly_legal(s, net.SCHEMA)
        dec = joint.decode(model, s, schema=net.SCHEMA)             # тот же декодер, что serving
        lab = dec["label"]
        hits += int(lab[yk["cells"]] == ip and lab["target"] == it and lab["weapon"] == iw)
    m = scores.metrics(model, samples)
    assert m["joint_decode_accuracy"] == pytest.approx(round(hits / len(samples), 3), abs=1e-9)


# ------------------------------------------------------------------ 3. baseline не подменяет joint
class _PeakedModel:
    """Стенд: НЕЗАВИСИМЫЙ argmax голов = (1,0,0) вне метки, joint argmax по A(s) = (0,0,0) = метка."""

    cfg = net.Config(hidden=4, head=2, seed=1)

    def head_logp(self, sample):
        d = spec_dims()
        pad = -1e30
        cells = [pad] * d["cells"]
        cells[1], cells[0] = -1.0, -1.2
        targets = [pad] * d["targets"]
        targets[0], targets[joint.NONE_TARGET] = -0.5, -1.5
        weapons = [pad] * d["weapons"]
        weapons[0], weapons[joint.NONE_WEAPON] = -0.5, -1.5
        return cells, targets, weapons, 0.0

    def predict(self, sample):
        cs, ts, ws, _v = self.head_logp(sample)
        return {"cell": max(range(len(cs)), key=cs.__getitem__),
                "target": max(range(len(ts)), key=ts.__getitem__),
                "weapon": max(range(len(ws)), key=ws.__getitem__), "value": 0.0}


def _assembled_sample():
    s = fake_samples(1, seed=7)[0]
    legal = [[[0] * (spec.K_WEAPONS + 1) for _ in range(spec.K_TARGETS + 1)]
             for _ in range(spec_dims()["cells"])]
    legal[0][joint.NONE_TARGET][joint.NONE_WEAPON] = 1
    legal[0][0][0] = 1                                    # метка: (клетка 0, цель 0, оружие 0)
    legal[1][joint.NONE_TARGET][joint.NONE_WEAPON] = 1    # клетка 1 легала ТОЛЬКО без атаки:
    return dict(s, legal=legal, y={"cell": 0, "target": 0, "weapon": 0})


def test_independent_accuracy_can_differ_and_does_not_replace_joint():
    s = _assembled_sample()
    m = scores.metrics(_PeakedModel(), [s])
    # независимый argmax = (1,0,0) — вне A(s) и вне метки: baseline-accuracy 0;
    # joint argmax по A(s) = метка (0,0,0): decode-accuracy 1. Метрики РАЗНЫЕ по построению.
    assert m["independent_baseline_accuracy"] == 0.0
    assert m["joint_decode_accuracy"] == 1.0
    assert m["cell"] == 0.0                               # голова клеток ошиблась независимо
    assert m["target"] == m["weapon"] == 1.0
    # joint.argmax действительно возвращает метку, а baseline — нет
    lcs, lts, lws, _v = _PeakedModel().head_logp(s)
    pick = joint.argmax(s["legal"], lcs, lts, lws, net.SCHEMA)
    assert (pick["cell"], pick["target"], pick["weapon"]) == (0, 0, 0)
    base = joint.independent_baseline({"cells": lcs, "targets": lts, "weapons": lws}, net.SCHEMA)
    assert (base["cell"], base["target"], base["weapon"]) == (1, 0, 0)
    assert not joint.is_jointly_legal(base, s["legal"], net.SCHEMA)   # baseline-тройка вне A(s)


# ------------------------------------------------------------------ 4. loss эпохи vs батчи
def test_epoch_loss_weighting_independent_of_batch_split():
    cfg = net.Config(hidden=8, head=3, seed=1)
    samples = fake_samples(6, seed=9)
    whole = PurePolicy(cfg, copy.deepcopy(net.init_params(cfg, spec_dims())))
    full = whole.step_batch(samples, lr=0.0)["loss"]                 # lr=0: веса не тронуты
    part = PurePolicy(cfg, copy.deepcopy(net.init_params(cfg, spec_dims())))
    reps = [part.step_batch(chunk, lr=0.0) for chunk in
            (samples[0:3], samples[3:5], samples[5:6])]          # то же покрытие: 3+2+1=6
    agg = scores.epoch_loss(reps)
    assert agg["loss"] == pytest.approx(full, abs=2e-4)              # то же среднее по 6 примерам
    assert agg["n_samples"] == len(samples)
    assert part.params == whole.params                               # lr=0 ничего не сдвинул
    # «последний батч» — НЕ среднее: одиночный пример даёт другое число (ловушка старого лога)
    assert abs(reps[-1]["loss"] - full) > 1e-4


# ------------------------------------------------------------------ 5. отбор по min val_joint_nll
class StampedPolicy(PurePolicy):
    """pure-политик со штампом шага в valueB: видно, из какой эпохи лежат веса."""

    def __init__(self, cfg, params=None):
        super().__init__(cfg, params)
        self.steps = 0

    def step_batch(self, batch, lr=None):
        report = super().step_batch(batch, lr)
        self.steps += 1
        self.params["valueB"] = float(self.steps)
        return report


def test_best_checkpoint_is_min_joint_nll_not_last_not_baseline(cfg, samples, tmp_path,
                                                                 monkeypatch):
    """Кривая: joint_nll минимум на эпохе 3; независимая accuracy максимум на 5.
    Отбор обязан дать эпоху 3 (model_best != model.json по весам и по epoch)."""
    nll_curve = [3.0, 2.0, 1.0, 2.0, 4.0]
    base_curve = [0.1, 0.2, 0.3, 0.4, 0.9]

    def fake_metrics(model, chunk):
        i = max(1, model.steps) - 1
        return {"cell": 0.0, "target": 0.0, "weapon": 0.0,
                "independent_baseline_accuracy": base_curve[i],
                "joint_decode_accuracy": 1.0 - nll_curve[i] / 10.0,
                "joint_nll": nll_curve[i], "value_mae": 0.0, "value_mse": 0.0,
                "n": len(chunk), "n_joint": len(chunk)}

    paths.set_workspace(str(tmp_path))
    policy = StampedPolicy(cfg, net.init_params(cfg, spec_dims()))
    monkeypatch.setattr(train.backend, "build", lambda *a, **k: policy)
    monkeypatch.setattr(train, "metrics", fake_metrics)
    report = train.run(name="sel", samples=samples, cfg=cfg, epochs=5, batch=len(samples),
                       log=lambda *_a: None)
    summary = report["summary"]
    assert summary["best_metric"] == "val.joint_nll"
    assert summary["best_epoch"] == 3                       # argmin, не аргмакс accuracy (5)
    assert not summary["best_is_last"]
    directory = paths.run_dir("sel")
    best = json.loads(open(paths.file_in(directory, "model_best.json"), encoding="utf-8").read())
    last = json.loads(open(paths.file_in(directory, "model.json"), encoding="utf-8").read())
    assert best["params"]["valueB"] == 3.0 and last["params"]["valueB"] == 5.0
    assert best["metrics"]["selected_by"] == "val.joint_nll"


def test_train_refuses_selection_without_joint_nll(cfg, samples, tmp_path, monkeypatch):
    """Нет joint_nll (модель без head_logp/легала) — отбор падает ЯВНО, а не молча
    возвращается к независимой accuracy."""
    def blind_metrics(model, chunk):
        return {"cell": 0.0, "target": 0.0, "weapon": 0.0,
                "independent_baseline_accuracy": 0.5, "joint_decode_accuracy": None,
                "joint_nll": None, "value_mae": 0.0, "value_mse": 0.0,
                "n": len(chunk), "n_joint": 0}

    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(train, "metrics", blind_metrics)
    with pytest.raises(RuntimeError, match="joint_nll"):
        train.run(name="blind", samples=samples, cfg=cfg, kind="pure", epochs=1,
                  batch=4, log=lambda *_a: None)


# ------------------------------------------------------------------ 6. v2 не регрессирует
def test_v2_training_reports_new_metrics_and_selects_by_joint_nll(cfg, samples, tmp_path):
    paths.set_workspace(str(tmp_path))
    report = train.run(name="v2ok", samples=samples, cfg=cfg, kind="pure", epochs=2,
                       batch=4, log=lambda *_a: None)
    assert report["summary"]["best_metric"] == "val.joint_nll"
    for row in report["history"]:
        m = row["val"]
        assert m["joint_nll"] is not None and m["n_joint"] == m["n"]
        assert 0.0 <= m["joint_decode_accuracy"] <= 1.0
        assert 0.0 <= m["independent_baseline_accuracy"] <= 1.0
        assert "joint" not in m                             # старое обманчивое имя уходит
        assert row["n_samples"] > 0                         # обработаны ВСЕ примеры эпохи
        assert row["loss"] is not None                      # средний по эпохе, не «последний батч»
    # веса v2-политики отбор не ломает: лучшая эпоха в пределах 1..2
    assert 1 <= report["summary"]["best_epoch"] <= 2
