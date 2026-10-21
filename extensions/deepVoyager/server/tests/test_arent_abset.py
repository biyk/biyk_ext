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
