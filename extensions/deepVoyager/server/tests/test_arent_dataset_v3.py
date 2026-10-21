# tests/test_arent_dataset_v3.py — F-B.3a: генератор и BC-обучение схемы 3 сквозным путём.
#
# Проверяем Wiring, а не математику головы (её запирают test_arent_encode_v3/test_arent_net_schema):
# dataset.generate(schema=3) обязан прогнать сцены через sample_one_v3, пометить stats["schema"]=3
# и выдать образцы со schema==3/меткой plan; train.run на этих образцах обязан сохранить
# чекпойнт схемы 3 (dims=spec3, config.schema=3) без torch (pure) и не трогать боевые runs/.
import pytest

from arent import dataset, net, paths, spec3, train


def _v3_samples(count=12, seed=7, scenes=6):
    """Настоящая генерация схемы 3: независимые командные сцены -> sample_one_v3."""
    pool, manifest = dataset.scenario_sources(scenes, seed)
    assert pool, "генератор обязан выдать боеспособные командные сцены"
    samples, stats = dataset.generate(
        count=count, seed=seed, per_src=3, rounds_max=2, teacher_rounds=1, teacher_limit=0.5,
        use_live=False, include_arenas=False, scenario_pool=pool, scenario_manifest=manifest,
        schema=spec3.SCHEMA)
    return samples, stats


def test_generate_schema3_routes_to_plan_samples():
    samples, stats = _v3_samples()
    assert stats["schema"] == spec3.SCHEMA == 3
    assert samples, f"схема 3 не дала ни одного примера: skip={stats['skip']}"
    assert all(s["schema"] == 3 for s in samples)
    assert all(set(s["y"]) == {"plan", "target", "weapon"} for s in samples)
    # метка plan указывает на реальный активный слот перемещения
    for s in samples:
        assert 0 <= s["y"]["plan"] < spec3.K_MOVEPLAN
    # состояние/цели/оружие общие со схемой 2, а голова клеток — плановой ширины
    assert len(samples[0]["cells"][0]) == len(spec3.CELL3_FEATURES)


def test_generate_schema2_is_unchanged_cell_head():
    samples, stats = dataset.generate(
        count=4, seed=7, per_src=2, rounds_max=1, teacher_rounds=1, teacher_limit=0.5,
        use_live=False, scenario_pool=None)
    assert stats["schema"] == 2
    if samples:
        assert all(s["schema"] == 2 and "cell" in s["y"] for s in samples)


def test_bc_smoke_trains_and_saves_schema3(tmp_path):
    samples, _stats = _v3_samples()
    if len(samples) < 2:
        pytest.skip("мало примеров для smoke-обучения")
    prev = paths.workspace()
    paths.set_workspace(str(tmp_path))
    try:
        cfg = net.Config(schema=3, hidden=8, head=6, epochs=1, batch=4)
        result = train.run(name="v3smoke", samples=samples[:-1], val=samples[-1:], cfg=cfg,
                           kind="pure", log=lambda *a: None)
        assert result["summary"]["dims"] == spec3.dims3()
        assert result["summary"]["config"]["schema"] == 3
        checkpoint = net.load(result["checkpoint"], expect_schema=3)
        assert checkpoint["schema"] == 3 and checkpoint["config"]["schema"] == 3
    finally:
        paths.set_workspace(prev)


def test_train_rejects_v2_weights_for_schema3(tmp_path):
    # дообучение схемы 3 от чекпойнта схемы 2 обязан отвергнуться явной ошибкой схемы
    prev = paths.workspace()
    paths.set_workspace(str(tmp_path))
    try:
        v2 = net.save(backend_build(2), str(tmp_path / "v2.json"))
        cfg3 = net.Config(schema=3, hidden=8, head=6)
        with pytest.raises(RuntimeError, match="схем"):
            train._warm_params(cfg3, v2)
    finally:
        paths.set_workspace(prev)


def backend_build(schema):
    from arent import backend
    return backend.build(net.Config(schema=schema, hidden=8, head=6), kind="pure")
