# tests/test_arent_paired.py — парная статистика сравнения учителей (разности + bootstrap CI).
import pytest

from arent import paired


def _rows(names, metric, values):
    return [{"name": n, metric: v} for n, v in zip(names, values)]


def test_align_keeps_only_common_scenes():
    a = _rows(["x", "y", "z"], "rollout", [1, 2, 3])
    b = _rows(["y", "z", "w"], "rollout", [2, 4, 9])
    p = paired.align(a, b)
    assert set(p) == {"y", "z"}
    assert p["y"] == ({"name": "y", "rollout": 2}, {"name": "y", "rollout": 2})


def test_diff_series_is_a_minus_b():
    a = _rows(["x", "y"], "rollout", [10, 20])
    b = _rows(["x", "y"], "rollout", [4, 20])
    p = paired.align(a, b)
    assert paired.diff_series(p, "rollout") == [6.0, 0.0]


def test_paired_get_supports_derived_dmg_net():
    row = {"dmg_dealt": 12.0, "dmg_taken": 5.0}
    assert paired.paired_get(row, "dmg_net") == 7.0
    assert paired.paired_get({"rollout": -3}, "rollout") == -3.0
    assert paired.paired_get({"foo": None}, "rollout") is None


def test_bootstrap_ci_empty_series_has_no_interval():
    ci = paired.bootstrap_ci([])
    assert ci == {"n": 0, "mean": None, "ci_lo": None, "ci_hi": None, "positive_share": None}


def test_bootstrap_ci_brackets_mean_and_is_deterministic():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    c1 = paired.bootstrap_ci(vals, resamples=2000, seed=7)
    c2 = paired.bootstrap_ci(vals, resamples=2000, seed=7)
    assert c1 == c2                                    # тот же seed -> тот же интервал
    assert c1["n"] == len(vals)
    assert c1["mean"] == pytest.approx(4.5)
    assert c1["ci_lo"] <= c1["mean"] <= c1["ci_hi"]
    assert c1["positive_share"] == 1.0                 # все разности положительны


def test_summarize_paired_reports_direction_and_scenes():
    a = _rows(["p", "q", "r"], "clear", [1, 0, 1])
    b = _rows(["p", "q", "r"], "clear", [0, 0, 1])
    s = paired.summarize_paired(a, b, ["clear"], resamples=1000, seed=3)
    assert s["scenes"] == 3
    assert s["per_scenario_diff"]["p"]["clear"] == 1.0
    assert s["per_scenario_diff"]["r"]["clear"] == 0.0
    st = s["diff_stats"]["clear"]
    assert st["mean"] == pytest.approx(1 / 3, abs=1e-4)
    assert st["positive_share"] == pytest.approx(1 / 3, abs=1e-3)


def test_zero_covering_ci_signals_inconclusive():
    # симметричные разности: среднее ~0 -> интервал накрывает 0 (вывод предварительный)
    vals = [5.0, -5.0, 3.0, -3.0, 1.0, -1.0]
    ci = paired.bootstrap_ci(vals, resamples=2000, seed=11)
    assert abs(ci["mean"]) < 1e-9
    assert ci["ci_lo"] < 0 < ci["ci_hi"]
