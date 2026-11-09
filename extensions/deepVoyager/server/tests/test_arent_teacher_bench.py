# tests/test_arent_teacher_bench.py — Фаза A / A3: гонка внешних политик на stage43.
#
# Проверяем harness, а не силу: что race собирает ЧЕСТНУЮ пару прогонов (канон + учебный
# пул) на одном seed, кладёт оба в один отчёт с bootstrap-сводкой и пишет артефакт.
import json
import os

from arent import teacher_bench


def test_race_composes_canon_and_pool_on_ext_policies():
    rep = teacher_bench.race(teachers=("battlecast_baseline", "ja2_positioning"),
                             seed=20261020, canon_each=1, pool_each=1, cap=3,
                             rounds=4, teacher_rounds=1, ci_seed=7)
    assert rep["schema"] == "ext_race_v1"
    assert rep["teachers"] == ["battlecast_baseline", "ja2_positioning"]
    assert rep["canon"]["set_source"] == "stage43_canon"
    assert rep["pool"]["set_source"] == "stage43_pool"
    # cap ограничил набор: не больше 3 сцен на источник
    assert rep["canon"]["n_scenes"] <= 3 and rep["pool"]["n_scenes"] <= 3
    # сводка по обоим источникам и обоим учителям
    for src in ("canon", "pool"):
        assert set(rep["summary"][src]["per_teacher"]) == {"battlecast_baseline",
                                                           "ja2_positioning"}
        for name in rep["teachers"]:
            assert "clear_rate" in rep["summary"][src]["per_teacher"][name]
            assert "kill_rate" in rep["summary"][src]["per_teacher"][name]


def test_race_is_reproducible_same_fingerprints():
    a = teacher_bench.race(teachers=("battlecast_baseline", "ja2_positioning"),
                           seed=20261020, canon_each=1, cap=2, rounds=3)
    b = teacher_bench.race(teachers=("battlecast_baseline", "ja2_positioning"),
                           seed=20261020, canon_each=1, cap=2, rounds=3)
    assert a["canon"]["set_fingerprint"] == b["canon"]["set_fingerprint"]


def test_race_write_emits_json_artifact(tmp_path):
    rep = teacher_bench.race(teachers=("battlecast_baseline", "ja2_positioning"),
                             seed=20261020, canon_each=1, pool_each=1, cap=2, rounds=3)
    path = teacher_bench.write(rep, str(tmp_path))
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["schema"] == "ext_race_v1"
    assert on_disk["canon"]["set_fingerprint"] == rep["canon"]["set_fingerprint"]
