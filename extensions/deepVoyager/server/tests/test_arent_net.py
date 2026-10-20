# tests/test_arent_net.py — сеть политика: три маскируемые головы + value.
#
# Тесты идут на синтетических примерах (реальная генерация — секунды на состояние),
# но размеры векторов берём из spec, а формат чекпойнта — общий для pure-python и torch:
# обучение на 4060 и игра на машине без torch должны читать один и тот же файл.
import copy
import json
import os
import random

import pytest

from arent import bench, cli, net, paths, play, train
from arent.backend import available, build, describe, load_policy
from arent.pure_net import PurePolicy
from conftest import make_scene_payload
from playground.arena import load_arena


def _group(rng, real, size, total):
    return [[rng.uniform(-1, 1) for _ in range(size)] if i < real else [0.0] * size
            for i in range(total)]


def spec_dims():
    from arent import spec
    return spec.dims()


def fake_samples(n=6, seed=1, cells=3, targets=2, weapons=1):
    """Примеры правильной формы, но без учителя: быстро и детерминированно."""
    rng = random.Random(seed)
    d = spec_dims()
    out = []
    for _ in range(n):
        out.append({
            "schema": net.SCHEMA, "state": [rng.uniform(-1, 1) for _ in range(d["state"])],
            "cells": _group(rng, cells, d["cell_feat"], d["cells"]),
            "targets": _group(rng, targets, d["target_feat"], d["targets"]),
            "weapons": _group(rng, weapons, d["weapon_feat"], d["weapons"]),
            "y": {"cell": rng.randrange(cells), "target": rng.randrange(targets + 1) - 1,
                  "weapon": rng.randrange(weapons + 1) - 1},
            "value": round(rng.uniform(-1, 1), 3),
            "mask": {"cells": [1] * cells + [0] * (d["cells"] - cells),
                     "targets": [1] * targets + [0] * (d["targets"] - targets - 1) + [1],
                     "weapons": [1] * weapons + [0] * (d["weapons"] - weapons - 1) + [1]},
            "meta": {"src": "A"},
        })
    return out


@pytest.fixture
def cfg():
    return net.Config(hidden=16, head=4, seed=3)


@pytest.fixture
def samples():
    return fake_samples(6)


def test_config_survives_json_roundtrip():
    cfg = net.default_config()
    restored = net.Config.from_dict(json.loads(json.dumps(cfg.to_dict())))
    assert restored == cfg
    assert cfg.hidden > 0 and cfg.epochs > 0


def test_params_have_declared_shapes(cfg):
    d = spec_dims()
    p = net.init_params(cfg, d)
    assert len(p["trunk1"]) == cfg.hidden and len(p["trunk1"][0]) == d["state"]
    assert len(p["trunk2"]) == cfg.head and len(p["trunk2"][0]) == cfg.hidden
    for group in net.GROUPS:
        rows = p["headW"][group]
        assert len(rows) == cfg.head
        assert len(rows[0]) == cfg.head + net.slot_size(group)
        assert len(p["headU"][group]) == cfg.head
        assert len(p["headB"][group]) == cfg.head
    assert len(p["valueW"]) == cfg.head


def test_param_count_matches_the_actual_weights(cfg):
    """Отчёт о размере сети обязан совпадать с числом весов в файле инициализации."""
    def count(node):
        if isinstance(node, dict):
            return sum(count(v) for v in node.values())
        if isinstance(node, list):
            return sum(count(v) for v in node)
        return 1

    d = spec_dims()
    assert net.param_count(cfg, d) == count(net.init_params(cfg, d))


def test_predict_never_picks_a_padded_slot(cfg, samples):
    model = build(cfg, kind="pure")
    for sample in samples:
        out = model.predict(sample)
        assert 0 <= out["cell"] < sum(sample["mask"]["cells"])
        assert out["target"] in [i for i, m in enumerate(sample["mask"]["targets"]) if m]
        assert out["weapon"] in [i for i, m in enumerate(sample["mask"]["weapons"]) if m]
        assert isinstance(out["value"], float)


def test_masked_argmax_ignores_forbidden_slots():
    assert net.masked_argmax([0.1, 9.0, 0.2], [1, 0, 1]) == 2
    assert net.masked_argmax([0.1, 9.0, 0.2], [1, 1, 1]) == 1


def test_label_index_maps_no_choice_slots():
    total = spec_dims()["targets"]
    assert net.label_index(-1, total) == total - 1        # «не стрелять» — последний слот
    assert net.label_index(2, total) == 2


def test_checkpoint_roundtrip_keeps_predictions(cfg, samples, tmp_path):
    model = build(cfg, kind="pure")
    before = [model.predict(s) for s in samples]
    path = net.save(model, str(tmp_path / "model.json"), metrics={"n": len(samples)})
    reloaded = load_policy(path, kind="pure")
    assert [reloaded.predict(s) for s in samples] == before
    assert json.loads(open(path, encoding="utf-8").read())["schema"] == net.SCHEMA


def test_pure_policy_lowers_loss_on_a_small_batch(cfg, samples):
    model = PurePolicy(cfg, net.init_params(cfg, spec_dims()))
    first = model.step_batch(samples, lr=0.2)["loss"]
    last = first
    for _ in range(12):
        last = model.step_batch(samples, lr=0.2)["loss"]
    assert last < first


def test_metrics_report_per_head_accuracy(cfg, samples):
    model = build(cfg, kind="pure")
    m = train.metrics(model, samples)
    assert m["n"] == len(samples)
    assert 0.0 <= m["joint"] <= min(m["cell"], m["weapon"]) + 1e-9
    assert m["value_mae"] >= 0.0


def test_metrics_joint_is_one_when_every_head_is_right(samples):
    """Оракул, попадающий во все три индекса, обязан дать joint = 1 (иначе метрика врёт)."""
    class Oracle:
        def predict(self, sample):
            out = {net.Y_KEY[g]: net.y_index(sample, g) for g in net.GROUPS}
            return dict(out, value=sample["value"])

    m = train.metrics(Oracle(), samples)
    assert m["joint"] == 1.0 and m["cell"] == m["target"] == m["weapon"] == 1.0
    assert m["value_mae"] == 0.0


def test_train_run_writes_checkpoint_and_history(cfg, samples, tmp_path):
    paths.set_workspace(str(tmp_path))
    report = train.run(name="unit", samples=samples, cfg=cfg, kind="pure",
                       epochs=3, batch=3, log=lambda *_a: None)
    checkpoint = paths.run_dir("unit")
    assert report["checkpoint"].endswith("model.json")
    assert json.loads(open(paths.file_in(checkpoint, "summary.json"),
                           encoding="utf-8").read())["epochs"] == 3
    assert len(json.loads(open(paths.file_in(checkpoint, "history.json"),
                                encoding="utf-8").read())) == 3


def test_train_warm_start_keeps_checkpoint_weights(cfg, samples, tmp_path):
    """--warm продолжает веса из чекпойнта; без него старт всегда случайный.

    Шаг с lr=0 ничего не меняет, поэтому совпадение параметров доказывает, что
    дообучение именно прочитало runs/<имя>/model.json, а не инициализировалось заново.
    """
    paths.set_workspace(str(tmp_path))
    first = train.run(name="w1", samples=samples, cfg=cfg, kind="pure", epochs=5, batch=4,
                      log=lambda *_a: None)
    base = json.loads(open(first["checkpoint"], encoding="utf-8").read())["params"]
    scratch = train.run(name="w2", samples=samples, cfg=cfg, kind="pure", epochs=1, batch=4,
                        log=lambda *_a: None)
    warm = train.run(name="w3", samples=samples, cfg=cfg, kind="pure", warm="w1", epochs=1,
                     batch=4, lr=0.0, log=lambda *_a: None)
    kept = json.loads(open(warm["checkpoint"], encoding="utf-8").read())["params"]
    fresh = json.loads(open(scratch["checkpoint"], encoding="utf-8").read())["params"]
    assert kept == base
    assert fresh != base
    assert warm["summary"]["warm_from"].replace("\\", "/").endswith("w1/model.json")


def test_train_warm_rejects_weights_of_another_shape(cfg, samples, tmp_path):
    """Форма весов задаёт чекпойнт: молча учить hidden=8 поверх hidden=16 нельзя."""
    paths.set_workspace(str(tmp_path))
    train.run(name="w1", samples=samples, cfg=cfg, kind="pure", epochs=1, batch=4,
              log=lambda *_a: None)
    with pytest.raises(RuntimeError, match="hidden"):
        train.run(name="w2", samples=samples, cfg=net.Config(hidden=8, head=cfg.head, seed=3),
                  kind="pure", epochs=1, batch=4, warm="w1", log=lambda *_a: None)


def test_train_warm_reports_a_missing_checkpoint(cfg, samples, tmp_path):
    paths.set_workspace(str(tmp_path))
    with pytest.raises(RuntimeError, match="Чекпойнта нет"):
        train.run(name="w1", samples=samples, cfg=cfg, kind="pure", epochs=1, batch=4,
                  warm="нет_такого", log=lambda *_a: None)


def test_cli_train_exposes_the_warm_flag():
    assert cli.parser().parse_args(["train", "--warm", "bc1"]).warm == "bc1"


def test_play_act_decodes_into_plan_actions(samples, tmp_path):
    paths.set_workspace(str(tmp_path))
    cfg = net.Config(hidden=16, head=4, seed=5)
    report = train.run(name="unit", samples=samples, cfg=cfg, kind="pure",
                       epochs=1, batch=4, log=lambda *_a: None)
    model = load_policy(report["checkpoint"], kind="pure")
    out = play.act(model, load_arena("glass_cannon"))
    assert {"actions", "y", "value"} <= set(out)
    assert all(a["action"] in {"move", "target", "use"} for a in out["actions"])
    assert out["y"]["cell"] >= 0


def test_play_accepts_run_name_instead_of_a_path(samples, tmp_path):
    """--model unit должен находить runs/unit/model.json, а не требовать полный путь."""
    paths.set_workspace(str(tmp_path))
    train.run(name="unit", samples=samples, cfg=net.Config(hidden=8, head=2, seed=2),
              kind="pure", epochs=1, batch=4, log=lambda *_a: None)
    out = play.run(model_path="unit", arena="glass_cannon", log=lambda *_a: None)
    assert {"actions", "value"} <= set(out)


def test_play_act_actions_reference_only_scene_ids():
    from planner.action import DIRECTIONS
    model = build(net.Config(hidden=8, head=2, seed=1), kind="pure")
    sword = {"id": "sword-1", "name": "Меч", "damage": "1d6",
             "attackBonus": 2, "sureFt": 5, "doubtFt": 5}
    payload = make_scene_payload(weapons=[sword])
    out = play.act(model, payload)
    ids = {str(n["id"]) for n in payload["data"]["npcs"]}
    for a in out["actions"]:
        if a["action"] == "target":
            assert a["conf"]["id"] in ids
        elif a["action"] == "use":
            assert a["conf"]["itemId"] == sword["id"]
        else:
            assert a["conf"]["direction"] in DIRECTIONS
    assert set(out["names"]) >= {"cell", "target", "weapon"}
    assert isinstance(out["value"], float)


def test_backend_always_offers_pure():
    assert "pure" in available()
    info = describe()
    assert {"kind", "torch", "cuda", "python"} <= set(info)


@pytest.mark.skipif("torch" not in available(), reason="torch не установлен")
def test_torch_policy_shares_the_checkpoint_format(samples):
    from arent.torch_net import TorchPolicy
    cfg = net.Config(hidden=16, head=4, seed=3)
    d = spec_dims()
    policy = TorchPolicy(cfg, net.init_params(cfg, d))
    first = policy.step_batch(samples, lr=0.2)["loss"]
    assert first > 0.0
    assert len(policy.params["trunk1"]) == len(net.init_params(cfg, d)["trunk1"])
    pure = PurePolicy(cfg, policy.params)
    out = pure.predict(samples[0])
    assert 0 <= out["cell"] < sum(samples[0]["mask"]["cells"])


def test_cli_info_reports_workspace(capsys, tmp_path):
    paths.set_workspace(str(tmp_path))
    assert cli.main(["info"]) == 0
    text = capsys.readouterr().out
    assert "workspace" in text or "arent" in text


def test_cli_without_subcommand_fails():
    assert cli.main([]) != 0


# ------------------------------------------------------------------ лучший чекпойнт
class StampedPolicy(PurePolicy):
    """pure-политик, штампающий номер шага в valueB: видно, из какой эпохи лежат веса."""

    def __init__(self, cfg, params=None):
        super().__init__(cfg, params)
        self.steps = 0

    def step_batch(self, batch, lr=None):
        report = super().step_batch(batch, lr)
        self.steps += 1
        self.params["valueB"] = float(self.steps)
        return report


def _joint_by_epoch(model, chunk):
    """Фиксированные метрики: пик всегда на первой эпохе (шаги монотонно растут)."""
    return {"cell": 0.0, "target": 0.0, "weapon": 0.0, "joint": 1.0 / model.steps,
            "value_mae": 0.0, "n": len(chunk)}


def test_train_saves_best_and_last_checkpoints_separately(cfg, samples, tmp_path, monkeypatch):
    """model.json = последняя эпоха, model_best.json = лучшая: при переобучении они разные."""
    paths.set_workspace(str(tmp_path))
    policy = StampedPolicy(cfg, net.init_params(cfg, spec_dims()))
    monkeypatch.setattr(train.backend, "build", lambda *a, **k: policy)
    monkeypatch.setattr(train, "metrics", _joint_by_epoch)
    report = train.run(name="kb", samples=samples, cfg=cfg, epochs=3, batch=len(samples),
                       log=lambda *_a: None)
    directory = paths.run_dir("kb")
    best = json.loads(open(paths.file_in(directory, "model_best.json"), encoding="utf-8").read())
    last = json.loads(open(paths.file_in(directory, "model.json"), encoding="utf-8").read())
    assert best["params"]["valueB"] == 1.0 and last["params"]["valueB"] == 3.0
    assert best["metrics"]["which"] == "best" and best["metrics"]["epoch"] == 1
    assert report["summary"]["best_epoch"] == 1
    assert report["summary"]["best_metric"] == "val.joint"
    assert report["best_checkpoint"].endswith("model_best.json")


def test_train_writes_best_file_even_when_last_epoch_is_best(cfg, samples, tmp_path):
    """Одна эпоха: оба файла обязаны существовать и совпадать — скрипты не гадают."""
    paths.set_workspace(str(tmp_path))
    train.run(name="one", samples=samples, cfg=cfg, kind="pure", epochs=1,
              batch=len(samples), log=lambda *_a: None)
    directory = paths.run_dir("one")
    best = json.loads(open(paths.file_in(directory, "model_best.json"),
                           encoding="utf-8").read())["params"]
    last = json.loads(open(paths.file_in(directory, "model.json"), encoding="utf-8").read())["params"]
    assert best == last


def test_train_history_records_seconds_and_val_by_source(cfg, samples, tmp_path):
    """История по эпохам: время эпохи (первая на CUDA всегда долгая) и разбивка по состояниям.

    Разбивка по источникам — это проверка на забывание: после дообучения видно, не упала
    ли точность на старых аренах. Отдельный --val даёт замороженный набор таких сцен.
    """
    paths.set_workspace(str(tmp_path))
    marked = copy.deepcopy(samples)
    marked[4]["meta"]["arena"] = "old_arena"
    marked[5]["meta"]["arena"] = "new_arena"
    train.run(name="hist", samples=marked[:4], val=marked[4:], cfg=cfg, kind="pure",
              epochs=2, batch=4, log=lambda *_a: None)
    history = json.loads(open(paths.file_in(paths.run_dir("hist"), "history.json"),
                              encoding="utf-8").read())
    assert history[0]["sec"] >= 0.0
    assert {"old_arena", "new_arena"} <= set(history[0]["val_by"])


def test_train_val_override_keeps_old_scenarios_measurable(cfg, samples, tmp_path):
    """--val поверх старого датасета: метрика на прежних сценариях не теряется при дообучении."""
    paths.set_workspace(str(tmp_path))
    held_out = copy.deepcopy(samples[4:])
    report = train.run(name="ho", samples=samples[:4], val=held_out, cfg=cfg, kind="pure",
                       epochs=1, batch=4, log=lambda *_a: None)
    assert report["val"]["n"] == len(held_out)
    assert report["summary"]["val_source"] == "override"


def _loss_of(cfg, params, sample):
    """Потеря одного примера на весах params, без шага оптимизатора."""
    probe = PurePolicy(cfg, copy.deepcopy(params))
    report = {"loss": 0.0, "cell": 0.0, "target": 0.0, "weapon": 0.0, "value": 0.0}
    probe._accumulate(sample, report)
    return report["loss"]


def _leaf(params, path):
    node = params
    for key in path[:-1]:
        node = node[key]
    return node, path[-1]


def test_pure_gradients_match_finite_differences(samples):
    """Рукописный backward = численный градиент; этот тест идёт и без torch.

    Именно так выглядит ошибка, которую иначе ловит только прогон с torch: формула
    градиента headU однажды оказалась умноженной на relu(h_in) ещё раз.
    """
    cfg = net.Config(hidden=8, head=3, seed=1)
    params = net.init_params(cfg, spec_dims())
    sample = samples[0]
    model = PurePolicy(cfg, copy.deepcopy(params))
    model._accumulate(sample, {"loss": 0.0, "cell": 0.0, "target": 0.0, "weapon": 0.0,
                               "value": 0.0})
    eps = 1e-5
    for path in (("b1", 3), ("trunk2", 1, 2), ("valueW", 2), ("headU", "cells", 0),
                 ("headB", "cells", 1), ("headUB", "cells"), ("headW", "cells", 1, 2)):
        node, index = _leaf(params, path)
        analytic = _leaf(model.grad, path)[0][index]
        base = node[index]
        node[index] = base + eps
        up = _loss_of(cfg, params, sample)
        node[index] = base - eps
        down = _loss_of(cfg, params, sample)
        node[index] = base
        assert analytic == pytest.approx((up - down) / (2 * eps), rel=2e-3, abs=2e-4)


@pytest.mark.skipif("torch" not in available(), reason="torch не установлен")
def test_pure_and_torch_value_gradients_match(cfg, samples):
    """Стоимость взвешена одинаково у обоих бэкендов: иначе метрики несопоставимы.

    valueW получает градиент только от головы стоимости, headU — только от трёх
    кросс-энтропий, так что совпадение по обоим ключам закрывает и вес стоимости.
    """
    from arent.torch_net import TorchPolicy
    params = net.init_params(cfg, spec_dims())
    sample = samples[0]
    pure = PurePolicy(cfg, copy.deepcopy(params))
    pure._accumulate(sample, {"loss": 0.0, "cell": 0.0, "target": 0.0, "weapon": 0.0,
                              "value": 0.0})
    policy = TorchPolicy(cfg, copy.deepcopy(params))
    policy.optim.zero_grad(set_to_none=True)
    policy.step_batch([sample], lr=0.0)                    # Adam с нулевым шагом ничего не меняет
    assert pure.grad["valueW"] == pytest.approx(
        policy.layers["value"].weight.grad.squeeze(0).tolist(), rel=1e-2, abs=1e-4)
    assert pure.grad["headU"]["cells"] == pytest.approx(
        policy.layers["score"]["cells"].weight.grad.squeeze(0).tolist(), rel=1e-2, abs=1e-4)


@pytest.mark.skipif("torch" not in available(), reason="torch не установлен")
def test_train_device_override_reaches_the_model(cfg, samples, tmp_path):
    """--device обязан долходить до сети: без него не сравнить CPU и GPU на одних данных."""
    paths.set_workspace(str(tmp_path))
    report = train.run(name="dev", samples=samples, cfg=cfg, kind="torch", device="cpu",
                       epochs=1, batch=len(samples), log=lambda *_a: None)
    assert report["summary"]["device"] == "cpu"


def test_bench_times_each_backend_and_device(tmp_path, cfg, samples):
    paths.set_workspace(str(tmp_path))
    report = bench.run(samples=samples, cfg=cfg, epochs=1, batch=len(samples),
                       kinds=("pure",), log=lambda *_a: None)
    assert len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["kind"] == "pure" and row["seconds"] >= 0.0 and row["device"]
    assert report["fastest"]["kind"] == "pure"


def test_cli_exposes_device_and_bench():
    assert cli.parser().parse_args(["train", "--device", "cpu"]).device == "cpu"
    assert cli.parser().parse_args(["bench", "--epochs", "2"]).epochs == 2
    assert cli.parser().parse_args(["gen", "--append"]).append is True


# ------------------------------------------------------------------ регрессия упаковки 4060
# Причина прошлого провала: в bat-файлах вызывался `train ... --keep-best`, а CLI такого
# флага не знает -> argparse выходит с кодом 2, обучение не стартует, в архив ложится
# только bench.json. Лучшая модель пишется ВСЕГДА (train._finish), поэтому флаг не нужен.


def test_cli_accepts_the_real_train_command_without_keep_best():
    """Штатная команда AUTO.bat разбирается без ошибок (без --keep-best)."""
    ns = cli.parser().parse_args(["train", "--dataset", "bc1", "--warm", "bc1",
                                  "--name", "bc2", "--epochs", "200"])
    assert ns.cmd == "train" and ns.name == "bc2" and ns.epochs == 200 and ns.warm == "bc1"


def test_cli_no_longer_accepts_the_removed_keep_best_flag():
    """--keep-best больше не принимается: он ничего не делал и ломал запуск (аргпарсер)."""
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["train", "--name", "bc2", "--keep-best"])


def test_train_error_returns_nonzero_and_writes_no_run(tmp_path):
    """Сломанное обучение -> ненулевой код (батник остановится) и никаких файлов прогона."""
    paths.set_workspace(str(tmp_path))
    code = cli.main(["train", "--warm", "нет_такого_прогона", "--name", "err1"])
    assert code != 0
    # run_dir() сам создаёт каталог, поэтому проверяем именно отсутствие чекпойнта
    assert not os.path.exists(os.path.join(paths.runs_dir(), "err1", "model.json"))


def test_train_writes_nonempty_best_and_last(cfg, samples, tmp_path):
    """Успешный прогон оставляет четыре ненулевых артефакта: last, best, summary, history."""
    paths.set_workspace(str(tmp_path))
    train.run(name="ok", samples=samples, cfg=cfg, kind="pure", epochs=3, batch=4,
              log=lambda *_a: None)
    directory = paths.run_dir("ok")
    for name in ("model.json", "model_best.json", "summary.json", "history.json"):
        path = paths.file_in(directory, name)
        assert os.path.exists(path) and os.path.getsize(path) > 0


def test_best_checkpoint_matches_peak_val_epoch(cfg, samples, tmp_path):
    """model_best.json = веса ЭПОХИ с лучшим val.joint, а не последней эпохи."""
    paths.set_workspace(str(tmp_path))
    train.run(name="pk", samples=samples[:4], val=samples[4:], cfg=cfg, kind="pure",
              epochs=6, batch=4, log=lambda *_a: None)
    directory = paths.run_dir("pk")
    history = json.loads(open(paths.file_in(directory, "history.json"), encoding="utf-8").read())
    joints = [row["val"]["joint"] for row in history]
    top = max(joints)
    peak = next(index for index, value in enumerate(joints) if value == top)  # первый пик (строгий >)
    best = json.loads(open(paths.file_in(directory, "model_best.json"), encoding="utf-8").read())
    assert best["metrics"]["which"] == "best"
    assert best["metrics"]["epoch"] == history[peak]["epoch"]
    assert best["metrics"]["val"]["joint"] == top


@pytest.mark.skipif("torch" not in available(), reason="torch не установлен")
def test_pure_and_torch_grads_match_as_per_sample_mean_on_batch(cfg, samples):
    """На батче > 1 градиенты совпадают с точностью до усреднения: pure суммирует, torch
    берёт среднее. Проверяем, что pure/n == torch (значит это конвенция редукции, а не баг).
    """
    from arent.torch_net import TorchPolicy

    def flat(node):
        if isinstance(node, list):
            out = []
            for item in node:
                out.extend(flat(item))
            return out
        return [float(node)]

    params = net.init_params(cfg, spec_dims())
    batch = samples[:4]
    n = len(batch)
    pure = PurePolicy(cfg, copy.deepcopy(params))
    for sample in batch:
        pure._accumulate(sample, {"loss": 0.0, "cell": 0.0, "target": 0.0, "weapon": 0.0,
                                  "value": 0.0})
    policy = TorchPolicy(cfg, copy.deepcopy(params), device="cpu")
    policy.optim.zero_grad(set_to_none=True)
    policy.step_batch(batch, lr=0.0)                       # Adam lr=0: веса не тронуты, grads наполнены
    pairs = [("valueW", pure.grad["valueW"], policy.layers["value"].weight.grad.tolist()[0]),
             ("headU.cells", pure.grad["headU"]["cells"],
              policy.layers["score"]["cells"].weight.grad.tolist()[0]),
             ("trunk1", pure.grad["trunk1"], policy.layers["trunk1"].weight.grad.tolist()),
             ("b2", pure.grad["b2"], policy.layers["trunk2"].bias.grad.tolist())]
    for name, a, b in pairs:
        fa, fb = flat(a), flat(b)
        assert len(fa) == len(fb)
        mean_diff = max(abs(x / n - y) for x, y in zip(fa, fb))   # pure/SUM vs torch/MEAN
        assert mean_diff < 1e-5, (name, mean_diff)
        big = max(range(len(fb)), key=lambda i: abs(fb[i]))
        if abs(fb[big]) > 1e-6:                                    # чистая сумма = n * среднее
            assert abs(fa[big] / fb[big] - n) < 1e-3, (name, fa[big] / fb[big])
