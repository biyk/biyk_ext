# tests/test_arent_team_eval.py — приёмка «универсального солдата»: метрика win-rate КОМАНДЫ.
#
# Старый контур (evaluate.fight) мерит моноактора: герой + скриптовой foes_act, итог —
# «выжил/зачистил». Новый контур (team_eval): каждый живой юнит обеих сторон ходит ОДНОЙ
# политикой через PolyFightEnv (self-play), итог боя — исход команды (win/loss/draw/mutual)
# по TeamReward. Тестируем: исходы на синтетических сценах, ротация start_index (WP5) в
# прогоне, сводка долей, детерминизм (один seed -> идентичные бои) и отчёт с provenance
# по независимому набору ho_/ho2_ (set_tag='independent').
import json
import os

import pytest

from arent import dataset, team_eval
from conftest import make_npc, make_scene_payload, make_weapon

NOTHING_LABEL = {"cell": 0, "target": -1, "weapon": -1}
ATTACK_LABEL = {"cell": 0, "target": 0, "weapon": 0}


class _Stub:
    """«Политика»: всегда бьёт ближайшую цель (или не бьёт) — предсказуемый прогон."""

    def __init__(self, attack=True, name="stub"):
        self.attack, self.name = attack, name

    def predict(self, sample):
        return dict(ATTACK_LABEL if self.attack else NOTHING_LABEL, value=0.0)


def _npc(nid, col, disp, hp, ini, speed=30):
    return make_npc(nid, col * 50, 0, disposition=disp, hp=hp, speed=speed, initiative=ini)


def _finisher(vid, damage="1d6"):
    f2 = _npc(vid, 3, 1, 4, 10)
    f2["weapons"] = [make_weapon(vid + "sw", "меч", damage=damage, sure_ft=5)]
    return f2


def _scene_win():
    """Наши 30hp бьют F1(6hp)/F2(4hp) вплотную; те отвечают медленно — командный win."""
    a1, a2 = _npc("A1", 0, -1, 30, 20), _npc("A2", 2, -1, 30, 5)
    f1 = _npc("F1", 1, 1, 6, 15)
    payload = make_scene_payload(npcs=[a1, a2, f1, _finisher("F2")],
                                 weapons=[make_weapon("sword", damage="1d6+2")])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


def _scene_loss():
    """Наши по 4hp под мечами F1/F2 — команда гибнет раньше, чем успевает зачистить."""
    a1, a2 = _npc("A1", 0, -1, 4, 20), _npc("A2", 2, -1, 4, 5)
    f1 = _npc("F1", 1, 1, 60, 15)
    f1["weapons"] = [make_weapon("f1sw", "меч", damage="1d6", sure_ft=5)]
    payload = make_scene_payload(npcs=[a1, a2, f1, _finisher("F2")],
                                 weapons=[make_weapon("sword", damage="1d6+2")])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


def _scene_draw():
    """Враг далеко, медленный и с короткой рукой; политика не атакует — тишина -> пат."""
    a1 = _npc("A1", 0, -1, 30, 20)
    f1 = _npc("F1", 8, 1, 30, 15, speed=5)
    f1["reachFt"] = 5
    payload = make_scene_payload(npcs=[a1, f1],
                                 weapons=[make_weapon("sword", damage="1d6+2")])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


#--- 1. исходы командного боя ----------------------------------------------------
def test_team_fight_reports_win_when_foe_team_wiped():
    row = team_eval.team_fight(_Stub(), _scene_win(), rounds_cap=8)
    assert row["outcome"] == "win"
    assert row["terminated"] is True and row["foes_alive"] == 0
    assert row["rounds"] >= 1 and row["steps"] >= 2


def test_team_fight_reports_loss_when_our_team_wiped():
    row = team_eval.team_fight(_Stub(), _scene_loss(), rounds_cap=8)
    assert row["outcome"] == "loss" and row["ours_alive"] == 0


def test_team_fight_reports_draw_on_stalemate():
    row = team_eval.team_fight(_Stub(attack=False), _scene_draw(),
                               rounds_cap=20, draw_window=2)
    assert row["outcome"] == "draw" and row["terminated"] is True


def test_team_fight_open_when_rounds_cap_hits_first():
    row = team_eval.team_fight(_Stub(attack=False), _scene_draw(),
                               rounds_cap=1, draw_window=99)   # усечение раньше пата
    assert row["outcome"] == "open" and row["terminated"] is False


#--- 2. ротация стартового актёра (WP5) в eval-прогоне ----------------------------
def test_team_fight_start_index_shifts_first_actor():
    assert team_eval.team_fight(_Stub(attack=False), _scene_win(),
                                start_index=0)["start_actor"] == "A1"
    assert team_eval.team_fight(_Stub(attack=False), _scene_win(),
                                start_index=2)["start_actor"] == "F2"


def test_evaluate_sources_rotates_starts_across_replays():
    rows = team_eval.evaluate_sources(_Stub(attack=False), [("s", _scene_win())],
                                      rounds_cap=20, replays=3)
    assert [r["start_actor"] for r in rows] == ["A1", "F1", "F2"]


#--- 3. сводка долей исходов ------------------------------------------------------
def test_summarize_team_rates_over_outcomes():
    rows = [{"outcome": "win"}, {"outcome": "win"}, {"outcome": "loss"},
            {"outcome": "draw"}, {"outcome": "mutual"}, {"outcome": "open"}]
    s = team_eval.summarize_team(rows, model="stub")
    assert s["fights"] == 6
    assert s["win_rate"] == pytest.approx(2 / 6, abs=1e-3)
    assert s["loss_rate"] == pytest.approx(1 / 6, abs=1e-3)
    assert (s["draw_rate"], s["mutual_rate"], s["open_rate"]) == (pytest.approx(1 / 6, abs=1e-3),
                                                                   pytest.approx(1 / 6, abs=1e-3),
                                                                   pytest.approx(1 / 6, abs=1e-3))


#--- 4. детерминизм: один seed/вход -> идентичный бой -----------------------------
def test_team_fight_is_deterministic():
    first = team_eval.team_fight(_Stub(), _scene_win(), rounds_cap=8)
    second = team_eval.team_fight(_Stub(), _scene_win(), rounds_cap=8)
    assert first == second                                      # без дайсов: то же и то же


#--- 5. прогон по независимому набору с provenance --------------------------------
def test_run_reports_independent_set_with_provenance(tmp_path, monkeypatch):
    sources = [("ho_test_win", _scene_win()), ("ho2_test_loss", _scene_loss())]
    monkeypatch.setattr(dataset, "independent_sources", lambda *a, **k: list(sources))
    monkeypatch.setattr(team_eval.paths, "run_dir", lambda name: str(tmp_path))
    monkeypatch.setattr(team_eval.backend, "load_policy",
                        lambda path, kind: _Stub(name="stub"))
    model_file = tmp_path / "stub.json"
    model_file.write_text("{}", encoding="utf-8")
    out = os.path.join(str(tmp_path), "team_eval.json")
    report = team_eval.run(name="unit_test", model_path=str(model_file),
                           out=out, replays=1)
    assert report["provenance"]["set_tag"] == "independent"
    assert report["fights"] == 2 and report["win_rate"] == pytest.approx(0.5, abs=1e-3)
    with open(out, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["provenance"]["test_sources"] == ["ho2_test_loss", "ho_test_win"]


#--- 6. CLI-проводка --------------------------------------------------------
def test_cli_team_eval_defaults_to_independent_set():
    from arent.cli import parser
    ns = parser().parse_args(["team-eval"])
    assert ns.independent is True and ns.replays == 1 and ns.rounds == 8
    assert parser().parse_args(["team-eval", "--all-sources"]).independent is False
