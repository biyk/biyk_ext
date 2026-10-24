# tests/test_arent_stage6.py — ЭТАП 6: версии признаков v3 (1.2) и точность value (1.3).
#
# 1.2: SCHEMA=3 задаёт СЕМАНТИКУ действия, а версия ПРИЗНАКОВ головы клетки вынесена в
#      spec3.FEATURES_VERSION. Старая v3-конфигурация (до ЭТАПА 5: cell_feat=22, без метки
#      версии) обязана ОТВЕРГАТЬСЯ новым конвейером явно — и в чекпойнте (net.load), и в
#      выборке (dataset.load), — а не примешиваться молча. Новая (feat_version=3, 23 признака)
#      проходит. Старые артефакты не трогаем: проверяем именно отказ загрузки.
# 1.3: value BC-примера берётся из rollout(..., rounds=1), который исполняет ход ПОРЯДКОВО
#      (sim.advance_seq -> apply_actor_seq): удар резолвится из клетки атаки, отход меняет лишь
#      финальную клетку. Для плана attack_cell!=end_cell это точная оценка, а не свёрнутая
#      v2-аппроксимация (advance/apply_hero бьёт из финальной клетки). В2-план (все MOVE перед
#      USE) даёт ровно то же число — advance == advance_seq — поэтому v2-путь не тронут.
import json

import pytest

from conftest import make_npc, make_scene_payload, make_weapon
from planner.action import move_action, target_action, use_action
from planner.context import BattleContext
from planner.sim import Simulation
from planner.turns import rollout
from arent import backend, dataset, net, paths, spec3


def _adjacent_ctx():
    """Герой A вплотную к врагу B; меч reach 1. Тот же расклад, что в test_arent_moveplan_v3."""
    npcs = [make_npc("A", 250, 0, disposition=-1, hp=20),
            make_npc("B", 300, 0, disposition=1, hp=20, damage="1d8")]
    payload = {**make_scene_payload(npcs=npcs, weapons=[make_weapon("sword", sure_ft=5,
                          damage="1d6+2")]), "speed": 30, "src": "A", "token": "A"}
    return BattleContext.from_payload(payload)


#--- 1.2. версия признаков: конфигурация и различение старой/новой -----------
def test_feature_version_is_declared_and_stamped_in_dims():
    # SCHEMA остаётся семантикой действия (=3); версия признаков — отдельный номер (=3)
    assert spec3.SCHEMA == 3
    assert spec3.FEATURES_VERSION == 3
    assert spec3.CELL_FEAT_V1 == 22                     # ширина старой головы (до ЭТАПА 5)
    assert len(spec3.CELL3_FEATURES) == 23               # голова +coverLos/atChokeEnd (ЭТАП 4)
    d = net.dims_for(3)
    assert d["cell_feat"] == 23 and d["feat_version"] == spec3.FEATURES_VERSION
    assert net.feature_version(3) == spec3.FEATURES_VERSION and net.feature_version(2) == 1


def test_fresh_v3_checkpoint_loads_and_carries_feature_version(tmp_path):
    cfg = net.Config(schema=3, hidden=8, head=6)
    model = backend.build(cfg, kind="pure")
    path = net.save(model, str(tmp_path / "new_v3.json"))
    ckpt = net.load(path, expect_schema=3)
    assert ckpt["dims"]["feat_version"] == spec3.FEATURES_VERSION
    assert ckpt["dims"]["cell_feat"] == len(spec3.CELL3_FEATURES)


def test_old_v3_checkpoint_is_rejected(tmp_path):
    """Старый v3-чекпойнт (cell_feat=22 / нет метки версии) обязан отвергаться, а не грузиться."""
    cfg = net.Config(schema=3, hidden=8, head=6)
    model = backend.build(cfg, kind="pure")
    path = str(tmp_path / "old_v3.json")
    net.save(model, path)
    ckpt = json.load(open(path, encoding="utf-8"))

    # случай 1: отметки версии вообще нет (формат до ЭТАПА 5)
    legacy = dict(ckpt)
    legacy["dims"] = {k: v for k, v in ckpt["dims"].items()
                      if k not in ("feat_version", "cell_feat")}
    legacy["dims"]["cell_feat"] = spec3.CELL_FEAT_V1
    p_legacy = str(tmp_path / "legacy_no_stamp.json")
    json.dump(legacy, open(p_legacy, "w", encoding="utf-8"))
    with pytest.raises(ValueError, match="версии признаков|несовместим"):
        net.load(p_legacy, expect_schema=3)

    # случай 2: отметка есть, но старая (feat_version=1 / cell_feat=22)
    old_v1 = dict(ckpt)
    old_v1["dims"] = dict(ckpt["dims"], cell_feat=spec3.CELL_FEAT_V1, feat_version=1)
    p_old = str(tmp_path / "old_v1.json")
    json.dump(old_v1, open(p_old, "w", encoding="utf-8"))
    with pytest.raises(ValueError, match="несовместим"):
        net.load(p_old, expect_schema=3)


def test_v2_checkpoint_is_untouched_by_feature_guard(tmp_path):
    """v2-чекпойнт проходит (его признаки не тронуты) — guard срабатывает только на схему 3."""
    cfg = net.Config(schema=2, hidden=8, head=6)
    model = backend.build(cfg, kind="pure")
    path = net.save(model, str(tmp_path / "v2.json"))
    assert net.load(path, expect_schema=2)["schema"] == 2      # без ошибки версии признаков


#--- 1.2. выборка: совместимость при загрузке dataset.load -------------------
def _sample_row(schema, feat_version, cell_feat):
    cells = [[0.0] * cell_feat for _ in range(spec3.K_MOVEPLAN + 1 if schema == 3 else 1)]
    row = {"schema": schema, "cells": cells, "y": {"plan": 0, "target": 0, "weapon": 0}}
    if feat_version is not None:
        row["feat_version"] = feat_version
    return row


def test_dataset_rejects_old_v3_rows_accepts_new(tmp_path):
    new = _sample_row(3, spec3.FEATURES_VERSION, len(spec3.CELL3_FEATURES))
    p_new = tmp_path / "new.jsonl"
    p_new.write_text(json.dumps(new) + "\n", encoding="utf-8")
    assert len(dataset.load(str(p_new))) == 1                   # новый пример проходит

    old_no_stamp = _sample_row(3, None, spec3.CELL_FEAT_V1)     # до ЭТАПА 5: 22, без метки
    old_v1 = _sample_row(3, 1, spec3.CELL_FEAT_V1)              # явная старая версия
    p_old = tmp_path / "old.jsonl"
    p_old.write_text(json.dumps(old_no_stamp) + "\n", encoding="utf-8")
    with pytest.raises(dataset.SchemaMismatch):
        dataset.load(str(p_old))
    p_old2 = tmp_path / "old_v1.jsonl"
    p_old2.write_text(json.dumps(old_v1) + "\n", encoding="utf-8")
    with pytest.raises(dataset.SchemaMismatch):
        dataset.load(str(p_old2))

    # подмешивание старого к новому обязано остановить загрузку целиком (не молча пропустить)
    p_mix = tmp_path / "mix.jsonl"
    p_mix.write_text("\n".join(json.dumps(r) for r in (new, old_v1)) + "\n", encoding="utf-8")
    with pytest.raises(dataset.SchemaMismatch):
        dataset.load(str(p_mix))


def test_generated_v3_samples_survive_save_load_roundtrip(tmp_path):
    """Сквозная проверка: реальная v3-выборка штампуется feat_version и читается назад без отказа."""
    prev = paths.workspace()
    paths.set_workspace(str(tmp_path))
    try:
        pool, manifest = dataset.scenario_sources(4, 7)
        samples, _stats = dataset.generate(
            count=6, seed=7, per_src=2, rounds_max=2, teacher_rounds=1, teacher_limit=0.4,
            use_live=False, include_arenas=False, scenario_pool=pool,
            scenario_manifest=manifest, schema=spec3.SCHEMA)
        if not samples:
            pytest.skip("нет размеченных v3-состояний на крошечном пуле")
        assert all(s["feat_version"] == spec3.FEATURES_VERSION for s in samples)
        assert all(len(s["cells"][0]) == len(spec3.CELL3_FEATURES) for s in samples)
        dataset.save(samples, "roundtrip")
        back = dataset.load("roundtrip")                        # load не обязан бросить SchemaMismatch
        assert len(back) == len(samples)
    finally:
        paths.set_workspace(prev)


#--- 1.3. value: точная последовательная оценка для плана с отходом ----------
def test_rollout_value_uses_exact_sequential_transition():
    ctx = _adjacent_ctx()
    hurt = [target_action("B"), use_action("sword"), move_action("left"), move_action("left")]
    seq_state, seq_val = Simulation.of(ctx).advance_seq(hurt)
    col_state, col_val = Simulation.of(ctx).advance(hurt)
    # (a) метрика линии (то, что кладётся в labeled.value на rounds=1) = точная seq-оценка
    assert rollout(ctx, hurt, rounds=1) == pytest.approx(seq_val)
    # (b) семантика move-plan: удар из клетки атаки попадает, свёрнутый (из финальной) — нет,
    #     поэтому seq и collapsed — РАЗНЫЕ состояния; выборка обязана опираться на seq
    assert seq_state.hp["B"] < 20.0
    assert col_state.hp["B"] == pytest.approx(20.0)


def test_v2_move_then_attack_value_is_bit_identical_under_advance_seq():
    """В2-контракт (все MOVE перед USE): advance_seq == advance, значит v2-путь не тронут."""
    ctx = _adjacent_ctx()
    strike = [target_action("B"), move_action("left"), use_action("sword")]
    seq_state, seq_val = Simulation.of(ctx).advance_seq(strike)
    col_state, col_val = Simulation.of(ctx).advance(strike)
    assert seq_val == pytest.approx(col_val)
    assert seq_state.hp["B"] == pytest.approx(col_state.hp["B"])


def test_labeled_value_matches_advance_seq_for_real_teacher():
    """End-to-end: value реального учителя = advance_seq(actions)[1] (точность, а не аппрокс)."""
    from arent.teacher import Teacher
    ctx_payload = {**make_scene_payload(
        npcs=[make_npc("A", 250, 0, disposition=-1, hp=20, speed=60),
              make_npc("B", 300, 0, disposition=1, hp=20, damage="1d8")],
        weapons=[make_weapon("sword", sure_ft=5, damage="1d6+2")]),
        "speed": 60, "src": "A", "token": "A"}
    teacher = Teacher(rounds=1)
    labeled = teacher.label(ctx_payload)
    exact = Simulation.of(labeled.ctx).advance_seq(labeled.actions)[1]
    assert labeled.value == pytest.approx(exact)                # rounds=1: rollout == advance_seq
