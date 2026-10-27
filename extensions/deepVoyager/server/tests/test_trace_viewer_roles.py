# tests/test_trace_viewer_roles.py — сводка метрик по роли кандидата
# (parse_traces.aggregate_roles): нанёс/получил/очки + винрейт раздельно за героев и за
# врагов; дедуп боёв по battle_uid; legacy-бои без разбора сторон не портят сводку.
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_MOD = os.path.join(HERE, "..", "tools", "trace_viewer", "parse_traces.py")


def _load():
    spec = importlib.util.spec_from_file_location("parse_traces_mod", _MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _b(**kw):
    d = {"policy": "ppo", "candSide": "heroes", "outcome": "win",
         "dealt": 10.0, "taken": 4.0, "battleUid": None}
    d.update(kw)
    return d


def test_aggregate_roles_groups_by_policy_and_side():
    m = _load()
    rows = m.aggregate_roles([_b(candSide="heroes"), _b(candSide="foes", outcome="loss")])
    by = {(r["policy"], r["role"]): r for r in rows}
    assert by[("ppo", "heroes")]["fights"] == 1
    assert by[("ppo", "heroes")]["win_rate"] == 1.0
    assert by[("ppo", "foes")]["win_rate"] == 0.0
    assert by[("ppo", "heroes")]["mean_dealt"] == 10.0
    assert by[("ppo", "heroes")]["mean_taken"] == 4.0
    assert by[("ppo", "heroes")]["mean_points"] == 6.0


def test_aggregate_roles_dedups_by_battle_uid():
    m = _load()
    rows = m.aggregate_roles([_b(battleUid="u1"), _b(battleUid="u1")])
    assert sum(r["fights"] for r in rows) == 1


def test_aggregate_roles_skips_legacy_without_stats():
    m = _load()
    assert m.aggregate_roles([_b(dealt=None, taken=None)]) == []
