# tests/test_team_eval_duel_pool.py — матчбокс на ЯВНОМ пуле сцен без обращения к dataset.
#
# Этап 1 гоняет matchup на сгенерированных дуэлях (scenarios.generate_duels), которых НЕТ в
# боевом каталоге арен. run_matchup обязан принять готовый пул (name, payload) напрямую и НЕ
# трогать dataset.sources/independent_sources (иначе упрётся в пустой каталог). Это зеркалит
# уже имеющийся контракт rl.run(scenario_sources=...) для обучения.
from arent import dataset, team_eval, tactics_config
from arent.tactics_config import TacticsConfig
from conftest import make_npc, make_scene_payload, make_weapon


def _scene():
    a1 = make_npc("A1", 0, 0, disposition=-1, hp=30, speed=30, initiative=20)
    f1 = make_npc("F1", 50, 0, disposition=1, hp=12, speed=30, initiative=15)
    payload = make_scene_payload(npcs=[a1, f1], weapons=[make_weapon("sword", damage="1d6+2")])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


def _forbid_dataset(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("dataset не должен вызываться при явном пуле сцен")
    monkeypatch.setattr(dataset, "independent_sources", _boom)
    monkeypatch.setattr(dataset, "sources", _boom)


def test_run_matchup_consumes_explicit_pool_without_disk(tmp_path, monkeypatch):
    _forbid_dataset(monkeypatch)
    monkeypatch.setattr(team_eval.paths, "run_dir", lambda name: str(tmp_path))
    tactics_config.set_config(TacticsConfig(enabled_global=False))    # eval: shaping выкл
    try:
        report = team_eval.run_matchup("random", "random", name="m_pool", replays=1,
                                       scenario_sources=[("duel_x", _scene())])
    finally:
        tactics_config.set_config(None)
    assert {r["name"] for r in report["rows"]} == {"duel_x"}          # поданы ровно наши сцены
    assert report["fights"] >= 2                                      # side-swap: обе расстановки
    for row in report["rows"]:
        assert row["illegal_proposals"] == 0                          # random ходит легально
