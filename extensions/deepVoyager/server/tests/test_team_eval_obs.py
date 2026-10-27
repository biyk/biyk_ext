# tests/test_team_eval_obs.py — дамп входа модели (наблюдения шага) по obs_trace.
#
# Вьюер по клику показывает JSON, который реально ушёл в политику на шаге. Инварианты
# дампера (team_eval.fight_teams):
#   obs_trace="off" (по умолчанию) — в шагах НЕТ obs_input, дампы бит-в-бит прежние;
#   obs_trace="cand" — obs_input только на шагах side=="cand";
#   obs_trace="all" — obs_input на каждом шаге;
#   obs_input JSON-сериализуем и содержит legal-маску (то, что видит модель);
#   запись наблюдения НЕ влияет на бой: строки совпадают побитово с off- прогоном.
import json

from arent import team_eval
from conftest import make_npc, make_scene_payload, make_weapon


def _npc(nid, col, disp, hp, ini, speed=30):
    return make_npc(nid, col * 50, 0, disposition=disp, hp=hp, speed=speed, initiative=ini)


def _duel():
    """Милишники в 6 клетках: кандидат ходит, сближается, бьёт — шаги обеих сторон."""
    a1 = _npc("A1", 0, -1, 30, 20)
    f1 = _npc("F1", 6, 1, 30, 15)
    payload = make_scene_payload(npcs=[a1, f1],
                                 weapons=[make_weapon("sword", "меч", damage="1d6+2",
                                                      sure_ft=5)])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


def _fight(obs_trace=None):
    kw = dict(rich_trace=True, schema=3, rounds_cap=3)
    if obs_trace is not None:
        kw["obs_trace"] = obs_trace
    return team_eval.fight_teams(_duel(), "battlecast", "greedy", **kw)


def test_obs_off_by_default():
    for t in _fight()["trace"]:
        assert "obs_input" not in t


def test_obs_cand_only_candidate_steps():
    trace = _fight("cand")["trace"]
    assert any(t["side"] == "cand" for t in trace), "без хода кандидата тест ничего не проверяет"
    for t in trace:
        if t["side"] == "cand":
            assert "obs_input" in t
        else:
            assert "obs_input" not in t


def test_obs_all_marks_every_step():
    trace = _fight("all")["trace"]
    assert trace and all("obs_input" in t for t in trace)


def test_obs_input_is_json_and_has_legal():
    for t in _fight("cand")["trace"]:
        if "obs_input" not in t:
            continue
        oi = t["obs_input"]
        assert "legal" in oi, "obs_input обязан включать joint-маску легальности A(s)"
        json.dumps(oi)                      # сериализуемость без default= — как в sidecar


def test_obs_trace_does_not_change_the_fight():
    off = _fight()                                          # obs_trace по умолчанию off
    cand = _fight("cand")
    for t in cand["trace"]:
        t.pop("obs_input", None)
    assert cand == off, "запись наблюдения не должна влиять на ход боя и метрики"
