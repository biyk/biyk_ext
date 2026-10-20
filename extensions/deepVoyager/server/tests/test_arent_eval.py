# tests/test_arent_eval.py — долгий горизонт как метрика: политика играет весь бой.
#
# Проверяем не «красивые числа», а инварианты evaluate.fight/summarize/run: агрессивная
# политика явно лучше бездействия по накопленной ценности и зачистке, прогон детерминирован
# по состоянию, сводка считает доли, а run пишет eval.json и умеет падать без сцен/чекпойнта.
import json
import os

import pytest

from arent import backend, evaluate, paths
from conftest import make_npc, make_scene_payload, make_weapon


class StubPolicy:
    """Мини-политика: predict всегда возвращает одну и ту же тройку индексов + value."""
    name = "stub"

    def __init__(self, choice):
        self.choice = dict(choice)

    def predict(self, sample):                       # sample нам не нужен — выбор фиксирован
        return dict(self.choice)


def _fight_scene(foe_hp=1, hero_hp=50):
    """Герой A в (0,0) с мечом; враг B впритык (0,1); герой живучий, враг хрупкий."""
    hero = make_npc("A", 0, 0, disposition=-1, hp=hero_hp, speed=30, damage="1d8")
    foe = make_npc("B", 50, 0, disposition=1, hp=foe_hp, speed=0, damage="1d8")
    return make_scene_payload(npcs=[hero, foe],
                              weapons=[make_weapon("sword", damage="1d6+2")], token="B")


ATTACK = {"cell": 0, "target": 0, "weapon": 0}       # стоять, целиться в B, бить мечом
NOTHING = {"cell": 0, "target": -1, "weapon": -1}    # «ни цели», «не атаковать»


def test_fight_attack_policy_clears_the_foe():
    row = evaluate.fight(StubPolicy(ATTACK), _fight_scene(), rounds=8)
    assert row["cleared"] is True and row["survived"] is True
    assert row["foes_left"] == 0 and row["rounds"] == 1


def test_fight_doing_nothing_never_clears_and_scores_less():
    attack = evaluate.fight(StubPolicy(ATTACK), _fight_scene(), rounds=8)
    passive = evaluate.fight(StubPolicy(NOTHING), _fight_scene(), rounds=8)
    assert passive["cleared"] is False and passive["survived"] is True
    assert attack["value"] > passive["value"]


def test_fight_is_deterministic_for_a_fixed_policy():
    payload = _fight_scene()
    policy = StubPolicy(ATTACK)
    assert evaluate.fight(policy, payload, rounds=8) == evaluate.fight(policy, payload, rounds=8)


def test_fight_stops_when_the_hero_is_outmatched():
    # хрупкий герой против живучего врага: безддействие ведёт к гибели, бой короток
    weak = _fight_scene(foe_hp=50, hero_hp=1)
    row = evaluate.fight(StubPolicy(NOTHING), weak, rounds=8)
    assert row["survived"] is False and row["rounds"] >= 1


def test_summarize_reports_rates_over_rows():
    rows = [
        {"rounds": 1, "value": 30.0, "survived": True, "cleared": True, "foes": 1, "foes_left": 0},
        {"rounds": 8, "value": -10.0, "survived": True, "cleared": False, "foes": 1, "foes_left": 1},
        {"rounds": 3, "value": 5.0, "survived": False, "cleared": False, "foes": 2, "foes_left": 1},
    ]
    s = evaluate.summarize(rows, model="stub", rounds_cap=8)
    assert s["fights"] == 3 and s["survival_rate"] == 0.667
    assert s["clear_rate"] == 0.333
    assert s["mean_value"] == pytest.approx(round((30.0 - 10.0 + 5.0) / 3, 3))
    assert s["model"] == "stub" and s["rounds_cap"] == 8


def test_summarize_handles_no_rows():
    s = evaluate.summarize([], model="stub")
    assert s["fights"] == 0 and s["mean_value"] == 0.0
    assert s["survival_rate"] == 0.0 and s["clear_rate"] == 0.0


def test_run_plays_all_sources_and_writes_eval_json(tmp_path, monkeypatch):
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(backend, "load_policy", lambda path, kind="auto": StubPolicy(ATTACK))
    monkeypatch.setattr(evaluate, "_sources", lambda arenas, use_live: [("arenaA", _fight_scene())])
    ckpt = paths.file_in(paths.run_dir("unit_model"), "model.json")
    with open(ckpt, "w", encoding="utf-8") as f:
        f.write("{}")
    report = evaluate.run(name="unit", model_path=ckpt, log=lambda *a: None)
    assert report["fights"] == 1 and report["clear_rate"] == 1.0
    out = os.path.join(str(tmp_path), "runs", "unit", "eval.json")
    assert os.path.exists(out)
    with open(out, encoding="utf-8") as f:
        assert json.load(f)["rows"][0]["name"] == "arenaA"


def test_run_without_checkpoint_raises(tmp_path, monkeypatch):
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(evaluate.play, "latest_checkpoint", lambda name=None: None)
    with pytest.raises(RuntimeError):
        evaluate.run(model_path=None)


def test_run_without_sources_raises(tmp_path, monkeypatch):
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(backend, "load_policy", lambda path, kind="auto": StubPolicy(ATTACK))
    monkeypatch.setattr(evaluate, "_sources", lambda arenas, use_live: [])
    with pytest.raises(RuntimeError):
        evaluate.run(name="empty", model_path="whatever", log=lambda *a: None)


def test_run_resolves_model_by_run_name(tmp_path, monkeypatch):
    # --model принимает ИМЯ прогона: runs/<имя>/model.json, а не только путь к файлу.
    paths.set_workspace(str(tmp_path))
    seen = {}
    monkeypatch.setattr(backend, "load_policy",
                        lambda path, kind="auto": seen.update(path=path) or StubPolicy(ATTACK))
    monkeypatch.setattr(evaluate, "_sources", lambda arenas, use_live: [("arenaA", _fight_scene())])
    real = paths.file_in(paths.run_dir("runA"), "model.json")
    with open(real, "w", encoding="utf-8") as f:
        f.write("{}")
    report = evaluate.run(name="unit", model_path="runA", log=lambda *a: None)
    assert report["fights"] == 1
    assert seen["path"] == real                                 # имя развёрнуто в реальный путь


def test_run_with_unknown_model_name_raises(tmp_path, monkeypatch):
    # имя прогона, у которого нет чекпойнта, должно падать, а не молча брать попавшийся файл
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(evaluate, "_sources", lambda arenas, use_live: [("arenaA", _fight_scene())])
    with pytest.raises(RuntimeError):
        evaluate.run(name="unit", model_path="ghost", log=lambda *a: None)
