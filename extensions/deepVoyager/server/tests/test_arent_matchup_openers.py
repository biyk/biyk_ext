# tests/test_arent_matchup_openers.py — контролируемая альтернатива первого хода (Этап 2).
#
# matchup_sources получает измерение «открывающий»: на каждую расстановку ролей
# (кандидат hero/foes) бой играется дважды — в одном лидер команды кандидата получает
# явную инициативу выше всех (90 против 10, без броска d20), в другом — наоборот.
# Порядок хода детерминирован и симметричен по построению, поэтому агрегатный
# win_rate свободен от конфаунда «победа за счёт первого хода». openings=False /
# openers=None — прежнее поведение (исторические прогоны Этапа 1 воспроизводимы).
from arent import team_eval
from conftest import make_npc, make_scene_payload, make_weapon


class _Stub:
    """Модель-заглушка: всегда бьёт (или не бьёт) — предсказуемый прогон через ModelController."""

    def __init__(self, attack=True, name="stub"):
        self.attack, self.name = attack, name

    def predict(self, sample):
        lab = {"cell": 0, "target": 0, "weapon": 0} if self.attack else \
              {"cell": 0, "target": -1, "weapon": -1}
        return dict(lab, value=0.0)


def _duel():
    """Дуэль 1v1 в упор: src=A1 (hero-команда, disp=-1), F1 (foes-команда, disp=1)."""
    a1 = make_npc("A1", 0, 0, disposition=-1, hp=30, speed=30, initiative=3)
    f1 = make_npc("F1", 50, 0, disposition=1, hp=30, speed=30, initiative=4)
    payload = make_scene_payload(npcs=[a1, f1],
                                 weapons=[make_weapon("sword", damage="1d6+2", sure_ft=5)])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


def _order(payload):
    from planner.context import BattleContext
    from planner.sim import Simulation
    return Simulation.of(BattleContext.from_payload(payload)).living_in_order


def test_opener_forces_candidate_side_first():
    p = team_eval._apply_candidate_opener(_duel(), candidate_is_foes=False, opens=True)
    assert _order(p)[0] == "A1"                      # команда кандидата (hero) открывает
    q = team_eval._apply_candidate_opener(_duel(), candidate_is_foes=False, opens=False)
    assert _order(q)[0] == "F1"                      # зеркально: открывает соперник


def test_opener_follows_candidate_side():
    """candidate_is_foes=True: сторона кандидата — foes, открыть должен F1."""
    p = team_eval._apply_candidate_opener(_duel(), candidate_is_foes=True, opens=True)
    assert _order(p)[0] == "F1"
    q = team_eval._apply_candidate_opener(_duel(), candidate_is_foes=True, opens=False)
    assert _order(q)[0] == "A1"


def test_opener_does_not_mutate_input():
    src = _duel()
    team_eval._apply_candidate_opener(src, candidate_is_foes=False, opens=True)
    assert src["data"]["npcs"][0]["initiative"] == 3   # исходный payload цел (только копия)


def test_fight_teams_records_opener():
    row = team_eval.fight_teams(_duel(), _Stub(), _Stub(), rounds_cap=4, opens=True)
    # по построению открывающий = init 90 у команды кандидата -> первый шаг за кандидатом
    assert row["candidate_opened"] is True
    off = team_eval.fight_teams(_duel(), _Stub(), _Stub(), rounds_cap=4)
    assert off["candidate_opened"] is None             # прежнее поведение: метки нет


def test_matchup_sources_doubles_rows_with_openers():
    rows = team_eval.matchup_sources(_Stub(), _Stub(), [("w", _duel())], replays=1,
                                     openings=True)
    assert len(rows) == 4                                # роль(2) × открывающий(2)
    assert sorted(r["candidate_opened"] for r in rows) == [False, False, True, True]
    for r in rows:                                       # метка согласована с ролью и стартом
        first_is_cand = (r["start_actor"] == "A1") == (not r["candidate_is_foes"])
        assert bool(r["candidate_opened"]) == first_is_cand


def test_matchup_sources_no_openings_keeps_legacy_rows():
    rows = team_eval.matchup_sources(_Stub(), _Stub(), [("w", _duel())], replays=1,
                                     openings=False)
    assert len(rows) == 2                                # прежнее поведение Этапа 1
    assert all(r["candidate_opened"] is None for r in rows)
