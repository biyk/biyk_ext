# tests/test_tactics_eval_counters.py — трасс-счётчики в eval-контуре (§1.1 train-only, §11).
#
# Проверяем два ключевых свойства приёмки Gate 0 для боевого контур team_eval:
#   1) record_only НЕ течёт в награду: итог/сумма reward совпадают побитово с прогоном без
#      счётчиков (честный eval — то, чем меряют «универсального солдата»);
#   2) counters непустой: детекторы видят ground-truth трасса и собирают applicable/fired.
import pytest

from arent import tactics_config, team_eval
from arent.tactics import Penalty, Tag
from arent.tactics_config import TacticsConfig
from arent.tactics_counters import Counters
from conftest import make_npc, make_scene_payload, make_weapon

ATTACK_LABEL = {"cell": 0, "target": 0, "weapon": 0}


class _Stub:
    """Всегда бьёт — детерминированная политика для ModelController."""

    name = "stub"

    def predict(self, sample):
        return dict(ATTACK_LABEL, value=0.0)


def _npc(nid, col, disp, hp, ini, speed=30):
    return make_npc(nid, col * 50, 0, disposition=disp, hp=hp, speed=speed, initiative=ini)


def _scene():
    a1, a2 = _npc("A1", 0, -1, 30, 20), _npc("A2", 2, -1, 30, 5)
    f1 = _npc("F1", 1, 1, 6, 15)
    f2 = _npc("F2", 3, 1, 4, 10)
    f2["weapons"] = [make_weapon("F2sw", "меч", damage="1d6", sure_ft=5)]
    payload = make_scene_payload(npcs=[a1, a2, f1, f2],
                                 weapons=[make_weapon("sword", damage="1d6+2")])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


@pytest.fixture
def shaped():
    """Включаем tactics с содержательными весами; после теста снимаем (изоляция от чужого points.json)."""
    cfg = TacticsConfig(enabled_global=True, cap_of_win=0.3,
                        weights={Tag.no_idle.value: 1.0, Tag.focus_wounded.value: 1.0},
                        penalties={Penalty.spread_fire.value: -1.0})
    tactics_config.set_config(cfg)
    yield cfg
    tactics_config.set_config(None)


def test_record_only_does_not_change_reward(shaped):
    clean = team_eval.fight_teams(_scene(), _Stub(), _Stub(), rounds_cap=8)
    with_counters = team_eval.fight_teams(_scene(), _Stub(), _Stub(), rounds_cap=8,
                                          counters=Counters())
    assert with_counters["reward"] == clean["reward"]        # shaping не потёк в награду (§1.1)
    assert with_counters["outcome"] == clean["outcome"] == "win"


def test_counters_nonempty_from_eval_trace(shaped):
    counters = Counters()
    team_eval.fight_teams(_scene(), _Stub(), _Stub(), rounds_cap=8, counters=counters)
    assert counters.steps > 0
    agg = counters.to_dict()["tactics"]
    assert agg                                             # хотя бы один ключ собран
    assert agg[Tag.no_idle.value]["applicable"] > 0         # атака => применимость непустая


def test_matchup_counters_record_only_candidate_steps(shaped):
    """follow_rate мерит КАНДИДАТА, а не соперника (§8-I/§11.3).

    В matchup кандидат vs фиксированный соперник счётчики должны агрегировать ТОЛЬКО
    шаги кандидата: инвариант counters.steps == row.candidate_steps (а не row.steps,
    где учтены оба фронта). Иначе пустые ходы random-соперника заражают no_idle."""
    counters = Counters()
    row = team_eval.fight_teams(_scene(), _Stub(), "random", rounds_cap=12,
                                counters=counters)
    assert row["candidate_steps"] > 0
    assert row["steps"] >= row["candidate_steps"]
    assert counters.steps == row["candidate_steps"]
    assert counters.to_dict()["steps"] == row["candidate_steps"]


def test_matchup_run_embeds_tactics_block(shaped, tmp_path, monkeypatch):
    from arent import dataset
    monkeypatch.setattr(dataset, "independent_sources",
                        lambda *a, **k: [("ho_test_win", _scene())])
    monkeypatch.setattr(team_eval.paths, "run_dir", lambda name: str(tmp_path))
    report = team_eval.run_matchup(_Stub(), _Stub(), name="unit_matchup",
                                   independent=True, use_tactics=True)
    assert "tactics" in report and report["tactics"]["steps"] > 0
