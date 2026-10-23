# tests/test_arent_dataset_label_core.py — общий core разметки: payload-вход и ctx-вход дают одно.
#
# DAgger строит примеры из ЖИВЫХ состояний (ctx из среды), а генерация стартовых сцен — из
# payload. Чтобы обе дорожки кормили один и тот же train.run, sample_one_v3 обязан быть тонкой
# обёрткой над sample_from_labeled_v3(name, labeled, meta, initiative): идентичный пример
# (state/cells/mask/y/meta.actions) при том же Labeled. Проверяем тождество обоих входов.
from arent import dataset, spec3
from arent.battlecast import BattlecastTeacher
from arent.teacher import Teacher
from planner.context import BattleContext
from planner.sim import Simulation


def _first_scene_pool():
    pool, _ = dataset.scenario_sources(6, 7)
    return pool


def test_sample_from_labeled_equals_sample_one_v3():
    pool = _first_scene_pool()
    assert pool, "нет боеспособных сцен для проверки"
    name, payload = pool[0]
    teacher = Teacher(rounds=1, time_limit_sec=0.5)
    order = Simulation.of(BattleContext.from_payload(payload), env_seed=7).initiative_order
    meta = {"arena": name}
    s_ref, r_ref = dataset.sample_one_v3(name, payload, teacher, meta, order)
    assert r_ref == "ok", f"базовая разметка не вышла: {r_ref}"
    labeled = teacher.label(payload)
    s_core, r_core = dataset.sample_from_labeled_v3(name, labeled, meta, order)
    assert r_core == "ok"
    assert s_core["schema"] == spec3.SCHEMA
    # тождество переименованного core старому пути: состояние, слоты, метка и план совпадают
    assert s_core["state"] == s_ref["state"]
    assert s_core["cells"] == s_ref["cells"]
    assert s_core["mask"] == s_ref["mask"]
    assert s_core["y"] == s_ref["y"]
    assert s_core["meta"]["actions"] == s_ref["meta"]["actions"]


def test_ctx_entry_yields_same_sample_as_payload_entry():
    # label_ctx(живой ctx) -> core даёт тот же пример, что label(payload) -> core: DAgger-вход чист.
    pool = _first_scene_pool()
    name, payload = pool[0]
    teacher = BattlecastTeacher()
    order = Simulation.of(BattleContext.from_payload(payload), env_seed=7).initiative_order
    meta = {"arena": name}
    from_payload, r1 = dataset.sample_from_labeled_v3(name, teacher.label(payload), meta, order)
    from_ctx, r2 = dataset.sample_from_labeled_v3(
        name, teacher.label_ctx(BattleContext.from_payload(payload)), meta, order)
    assert r1 == r2 == "ok"
    assert from_ctx["y"] == from_payload["y"]
    assert from_ctx["state"] == from_payload["state"]
