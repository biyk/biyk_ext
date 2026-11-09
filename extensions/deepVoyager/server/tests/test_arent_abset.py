# tests/test_arent_abset.py — A/B на фиксированном независимом наборе (структурные сцены).
from arent import abset


def test_build_set_is_deterministic_and_excludes_holdout():
    a = abset.build_set(12, seed=20261020)
    b = abset.build_set(12, seed=20261020)
    assert [n for n, _p, _x in a] == [n for n, _p, _x in b]          # один seed -> один набор
    assert len(a) == 12
    assert all(not n.startswith("ho_") for n, _p, _x in a)          # holdout не просачивается
    assert all(n.startswith("gen_") for n, _p, _x in a)


def test_fingerprint_is_stable_and_scene_specific():
    a = abset.build_set(10, seed=20261020)
    c = abset.build_set(10, seed=999)
    assert abset.fingerprint(a) == abset.fingerprint(a)
    assert abset.fingerprint(a) != abset.fingerprint(c)


def test_fight_reports_common_scale_rollout():
    name, payload, _params = abset.build_set(1, seed=20261020)[0]
    from arent.teachers import get_teacher
    impl = get_teacher("greedy", rounds=1, time_limit_sec=None)
    row = abset.fight(impl, payload, rounds=8)
    for k in ("survived", "cleared", "rounds", "rollout", "dmg_dealt", "dmg_taken", "foes_left"):
        assert k in row
    # шкала advance: смерть -150, урон -30/попадание — rollout в разумных пределах, не EV-сумма BC
    assert -1000.0 < row["rollout"] < 1000.0


def test_run_produces_paired_stats_and_per_scenario_rows():
    report = abset.run(count=8, seed=20261020, rounds=6, teacher_rounds=1,
                       teachers=("greedy", "battlecast"), ci_seed=7)
    assert report["n_scenes"] == 8
    assert report["holdout_excluded"] is True
    assert set(report["per_teacher"]) == {"greedy", "battlecast"}
    for name in ("greedy", "battlecast"):
        assert len(report["per_scenario"][name]) == 8
        assert report["per_teacher"][name]["coverage"]["states"] == 8
    paired = report["paired"]
    assert paired["scenes"] == 8
    assert "rollout" in paired["diff_stats"]
    st = paired["diff_stats"]["rollout"]
    assert st["n"] == 8 and st["ci_lo"] <= st["mean"] <= st["ci_hi"]


def test_depth_map_runs_greedy_at_lookahead_and_records_it():
    # greedy на штатной глубине (rounds=2) против однопроходного battlecast — воспроизводимо через run
    report = abset.run(count=3, seed=20261020, rounds=4, teacher_rounds=1,
                       teachers=("greedy", "battlecast"), depth_map={"greedy": 2})
    assert report["depths"]["greedy"]["rounds"] == 2
    assert report["depths"]["battlecast"]["rounds"] == 1
    assert report["per_teacher"]["greedy"]["fights"] == 3


def test_write_emits_fixed_set_and_result(tmp_path):
    report = abset.run(count=5, seed=20261020, rounds=5, teachers=("greedy", "battlecast"))
    out = abset.write(report, str(tmp_path))
    import json
    import os
    with open(out["set"], encoding="utf-8") as f:
        fixed = json.load(f)
    with open(out["result"], encoding="utf-8") as f:
        res = json.load(f)
    assert os.path.exists(out["result"])
    assert fixed["set_fingerprint"] == res["set_fingerprint"]
    assert len(fixed["scenes"]) == 5


# --- Фаза A / A2: тактические метрики (cgpt §6) поверх существующего ряда боя ---------
# Честно добавляем только то, что измеримо НАШЕЙ симуляцией: число действий, добивания,
# холостые раунды -> dmg_per_action / kill_rate / wasted_rate. cover-usage и OA-prevented
# не считаем (в planner их нет) — это зафиксировано как находка, а не выдуманная метрика.
def test_fight_row_carries_action_and_kill_counters():
    from arent.teachers import get_teacher
    _name, payload, _params = abset.build_set(1, seed=20261020)[0]
    impl = get_teacher("battlecast", rounds=1)
    row = abset.fight(impl, payload, rounds=8)
    for k in ("actions", "kills", "wasted"):
        assert k in row, f"в row нет счётчика {k}"
        assert isinstance(row[k], int) and row[k] >= 0
    # kills не может превышать число врагов на сцене
    assert row["kills"] <= row["foes"]


def test_agg_reports_derived_tactical_metrics():
    report = abset.run(count=6, seed=20261020, rounds=6, teacher_rounds=1,
                       teachers=("greedy", "battlecast"))
    for name in ("greedy", "battlecast"):
        agg = report["per_teacher"][name]
        for k in ("dmg_per_action", "kill_rate", "wasted_rate"):
            assert k in agg, f"в _agg нет {k}"
        assert agg["dmg_per_action"] >= 0.0
        assert 0.0 <= agg["kill_rate"] <= 1.0
        assert 0.0 <= agg["wasted_rate"] <= 1.0


def test_paired_diff_includes_new_tactical_metrics():
    report = abset.run(count=6, seed=20261020, rounds=6, teachers=("greedy", "battlecast"))
    diff = report["paired"]["diff_stats"]
    for m in ("actions", "kills", "wasted"):
        assert m in diff, f"в paired.diff_stats нет метрики {m}"


# --- Фаза A / A3: гонка на структурном генераторе «1-4 на 1-4» (scenarios.stage43) ------
# build_set/run умеют брать набор не только из generate (total-сцены), но и из канона
# (честная «линейка») и учебного пула. count для stage43-источников = сцен НА пару (count_each).
def test_build_set_supports_stage43_sources_and_is_deterministic():
    canon = abset.build_set(1, seed=20261020, source="stage43_canon")
    again = abset.build_set(1, seed=20261020, source="stage43_canon")
    assert [n for n, _p, _x in canon] == [n for n, _p, _x in again]   # повтор идентичен
    assert canon, "канонный набор пуст — валидация сняла все сцены"
    assert all(n.startswith("s43w_") for n, _p, _x in canon)          # канон: s43w_*
    assert all(not n.startswith(("ho_",)) for n, _p, _x in canon)
    pool = abset.build_set(1, seed=20261020, source="stage43_pool")
    assert all(n.startswith(("s43_", "s43u_")) for n, _p, _x in pool)  # пул: s43_*/s43u_*


def test_build_set_rejects_unknown_source():
    import pytest
    with pytest.raises((KeyError, ValueError)):
        abset.build_set(1, seed=1, source="nope")


def test_run_on_canon_source_records_source_and_ext_policies():
    report = abset.run(count=1, seed=20261020, rounds=4, teacher_rounds=1,
                       source="stage43_canon", ci_seed=7,
                       teachers=("battlecast_baseline", "ja2_positioning"))
    assert report["set_source"] == "stage43_canon"
    assert report["n_scenes"] == len(report["fixed_set"]) > 0
    assert set(report["per_teacher"]) == {"battlecast_baseline", "ja2_positioning"}
    assert report["a_minus_b"] == "battlecast_baseline-ja2_positioning"
    # новые тактические метрики доступны и для внешних политик
    for name in report["teachers"]:
        agg = report["per_teacher"][name]
        for k in ("dmg_per_action", "kill_rate", "wasted_rate"):
            assert k in agg
