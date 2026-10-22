# tests/test_arent_team_matchup.py — командная оценка ДВУХ политик (Этап 1).
#
# Проверяем то, чего не давал одиночный контур evaluate.fight (герой + скриптовой foes_act,
# союзники заморожены): в team-matchup КАЖДЫЙ живой актёр обеих команд получает ход своей
# политикой через ТОТ ЖЕ PolyFightEnv, что и обучение. Кандидат ведёт одну сторону, соперник
# — другую; стороны меняются местами (A/B-swap), а итог разворачивается к перспективе
# кандидата. Никакого обучения/генерации здесь нет — только прогон фиксированных политик.
import pytest

from arent import team_eval
from conftest import make_npc, make_scene_payload, make_weapon

ATTACK_LABEL = {"cell": 0, "target": 0, "weapon": 0}
NOTHING_LABEL = {"cell": 0, "target": -1, "weapon": -1}


class _Stub:
    """Модель-заглушка: всегда бьёт (или не бьёт) — предсказуемый прогон через ModelController."""

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
    """Наши 30hp (A1 ходит первым, A2 — союзник не-герой) бьют F1(6hp)/F2(4hp): командный win."""
    a1, a2 = _npc("A1", 0, -1, 30, 20), _npc("A2", 2, -1, 30, 5)
    f1 = _npc("F1", 1, 1, 6, 15)
    payload = make_scene_payload(npcs=[a1, a2, f1, _finisher("F2")],
                                 weapons=[make_weapon("sword", damage="1d6+2")])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


#--- 1. команда ходит ДВУМЯ политиками: обе стороны реально исполняют ходы ----------
def test_fight_teams_makes_both_teams_act():
    row = team_eval.fight_teams(_scene_win(), _Stub(), _Stub(), rounds_cap=8)
    assert row["outcome"] == "win" and row["raw_outcome"] == "win"
    assert row["candidate_steps"] > 0 and row["opponent_steps"] > 0      # ходили ОБЕ команды
    assert row["opponent_alive"] == 0                                    # вражеская команда зачищена
    sides = {t["side"] for t in row["trace"]}
    assert sides == {"cand", "opp"}                                      # журнал обеих сторон


def test_fight_teams_moves_non_hero_ally_under_candidate():
    """Ключевое отличие от одиночного контура: союзник не-герой (A2) сам получает ход."""
    row = team_eval.fight_teams(_scene_win(), _Stub(), _Stub(), rounds_cap=8, trace_limit=0)
    ally_actors = {t["actor"] for t in row["trace"] if t["side"] == "cand"}
    assert "A2" in ally_actors                                           # A2 != src, но ходил


def test_fight_teams_schema_and_env_are_team():
    row = team_eval.fight_teams(_scene_win(), "greedy", "battlecast", rounds_cap=8)
    assert row["schema"] == 2
    assert row["env_version"]["mode"] == "team-2policy"
    assert row["env_version"]["env"] == "PolyFightEnv"
    assert row["opponent_steps"] > 0                                     # соперник вёл свою команду


#--- 2. перспектива кандидата: смена сторон зеркалит win/loss ------------------------
def test_outcome_flips_when_candidate_switches_sides():
    a = team_eval.fight_teams(_scene_win(), _Stub(), _Stub(), candidate_is_foes=False, rounds_cap=8)
    b = team_eval.fight_teams(_scene_win(), _Stub(), _Stub(), candidate_is_foes=True, rounds_cap=8)
    assert a["raw_outcome"] == b["raw_outcome"]                          # один и тот же физический бой
    assert a["outcome"] == "win" and b["outcome"] == "loss"              # взгляд кандидата зеркален


#--- 3. недопустимое/нулевое действие ловится в журнале -----------------------------
def test_illegal_attack_is_legahzed_and_counted():
    """Цель жива, но оружие не достаёт -> legalize убирает weapon: chosen != executed."""
    a1 = _npc("A1", 0, -1, 30, 20)                                        # герой далеко
    f1 = _npc("F1", 8, 1, 30, 15, speed=5)                               # враг далеко
    payload = make_scene_payload(npcs=[a1, f1], weapons=[make_weapon("dag", damage="1d4", sure_ft=5)])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    row = team_eval.fight_teams(payload, _Stub(), _Stub(attack=False), rounds_cap=2)
    assert row["zero_damage_steps"] >= 1                                 # никто никого не достал


#--- 4. matchup: обе расстановки сторон на одной сцене ------------------------------
def test_matchup_sources_produces_both_side_assignments():
    rows = team_eval.matchup_sources(_Stub(), _Stub(), [("w", _scene_win())], replays=1)
    assert len(rows) == 2
    assert sorted(r["candidate_is_foes"] for r in rows) == [False, True]


def test_matchup_sources_no_swap_single_side():
    rows = team_eval.matchup_sources(_Stub(), _Stub(), [("w", _scene_win())],
                                     replays=1, swap_sides=False)
    assert len(rows) == 1 and rows[0]["candidate_is_foes"] is False


def test_summarize_matchup_has_side_blocks():
    rows = team_eval.matchup_sources(_Stub(), _Stub(), [("w", _scene_win())], replays=1)
    s = team_eval.summarize_matchup(rows)
    assert s["mode"] == "team-2policy" and s["fights"] == 2
    assert s["candidate_is_hero_team"]["fights"] == 1
    assert s["candidate_is_foe_team"]["fights"] == 1
    # симметричные политики на выигрышной сцене: кандидат выиграл, будучи нашей командой...
    assert s["candidate_is_hero_team"]["win_rate"] == pytest.approx(1.0)
    assert s["candidate_is_foe_team"]["loss_rate"] == pytest.approx(1.0)


#--- 5. детерминизм: одна сцена/вход -> идентичный бой ------------------------------
def test_fight_teams_is_deterministic():
    first = team_eval.fight_teams(_scene_win(), "greedy", "battlecast", rounds_cap=8)
    second = team_eval.fight_teams(_scene_win(), "greedy", "battlecast", rounds_cap=8)
    assert first == second


#--- 6. схема 3 (move-plan): те же две политики идут через apply_actor_seq ----------
def test_fight_teams_runs_schema3_without_error():
    row = team_eval.fight_teams(_scene_win(), "greedy", "greedy", rounds_cap=6, schema=3)
    assert row["schema"] == 3
    assert row["candidate_steps"] > 0 and row["opponent_steps"] > 0
    # метки схемы 3 используют ключ плана (plan), а не клетки (cell)
    for t in row["trace"]:
        assert set(t["chosen"]) >= {"plan", "target", "weapon"}


#--- 7. CLI-проводка ---------------------------------------------------------------
def test_cli_team_matchup_defaults():
    from arent.cli import parser
    ns = parser().parse_args(["team-matchup"])
    assert ns.candidate == "battlecast" and ns.opponent == "greedy"
    assert ns.swap_sides is True and ns.independent is True and ns.rounds == 8
    assert parser().parse_args(["team-matchup", "--no-swap"]).swap_sides is False
    assert parser().parse_args(["team-matchup", "--all-sources"]).independent is False


#--- 8. run_matchup пишет ОТДЕЛЬНЫЙ файл, не трогая team_eval.json -----------------
def test_run_matchup_writes_separate_file(tmp_path, monkeypatch):
    from arent import dataset
    sources = [("ho_test_win", _scene_win())]
    monkeypatch.setattr(dataset, "independent_sources", lambda *a, **k: list(sources))
    monkeypatch.setattr(team_eval.paths, "run_dir", lambda name: str(tmp_path))
    out = str(tmp_path / "team_matchup.json")
    report = team_eval.run_matchup("greedy", "battlecast", name="unit_matchup", out=out)
    assert report["mode"] == "team-2policy"
    assert report["provenance"]["set_tag"] == "independent"
    import json
    import os
    with open(out, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["candidate_id"].startswith("greedy")
    assert os.path.exists(out)
