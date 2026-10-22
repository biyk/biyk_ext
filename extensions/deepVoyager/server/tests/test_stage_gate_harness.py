# tests/test_stage_gate_harness.py — гарнитур gate-приёмки (§7): win/loss/draw/CI + PASS/FAIL.
#
# Проверяем, что stage_gate считает метрики по matchup-строкам (policy vs random с side-swap
# на N боёв) и выносит PASS/FAIL по порогам раздела 4: side-parity, min win, follow_rate
# (N/A при нулевой применимости = FAIL, §11.3), минимальное число боёв. Плюс сквозной прогон
# на РЕАЛЬНЫХ строках team_eval.matchup_sources (greedy vs random).
import os

from arent import stage_gate, team_eval
from conftest import make_npc, make_scene_payload, make_weapon

ATTACK_LABEL = {"cell": 0, "target": 0, "weapon": 0}


class _Stub:
    """Всегда бьёт — детерминированная «политика» для ModelController."""

    name = "stub"

    def predict(self, sample):
        return dict(ATTACK_LABEL, value=0.0)


def _row(outcome, cand_foes=False, name="s1"):
    return {"outcome": outcome, "candidate_is_foes": cand_foes, "name": name}


def _mixed_rows(win_hero=8, loss_hero=2, win_foes=7, loss_foes=3):
    rows = []
    for i in range(win_hero):
        rows.append(_row("win", cand_foes=False, name=f"h{i}"))
    for i in range(loss_hero):
        rows.append(_row("loss", cand_foes=False, name=f"hl{i}"))
    for i in range(win_foes):
        rows.append(_row("win", cand_foes=True, name=f"f{i}"))
    for i in range(loss_foes):
        rows.append(_row("loss", cand_foes=True, name=f"fl{i}"))
    return rows


# ------------------------------------------------------------------ чистые метрики
def test_win_loss_draw_exact_rates():
    rows = [_row("win"), _row("win"), _row("loss"), _row("draw"), _row("open")]
    wld = stage_gate.win_loss_draw(rows)
    assert wld["win"] == 0.4 and wld["loss"] == 0.2 and wld["draw"] == 0.2
    assert wld["mutual"] == 0.0 and wld["open"] == 0.2


def test_ci_for_win_is_deterministic_and_brackets_rate():
    rows = [_row("win") if i % 2 == 0 else _row("loss") for i in range(40)]
    a = stage_gate.ci_for_win(rows, resamples=500, seed=99)
    b = stage_gate.ci_for_win(rows, resamples=500, seed=99)
    assert a == b                                             # seed фиксирует CI (паритет §1.6)
    assert 0.0 <= a["ci_lo"] <= a["mean"] <= a["ci_hi"] <= 1.0
    assert a["mean"] == 0.5 and a["n"] == 40


def test_side_parity_balanced_vs_biased():
    balanced = _mixed_rows(win_hero=5, loss_hero=5, win_foes=5, loss_foes=5)
    sp = stage_gate.side_parity(balanced)
    assert sp["diff"] == 0.0                                  # равные доли -> паритет
    biased = _mixed_rows(win_hero=10, loss_hero=0, win_foes=2, loss_foes=8)
    assert stage_gate.side_parity(biased)["diff"] == 0.8       # advantage стороны hero


# ------------------------------------------------------------------ check_gate PASS/FAIL
def test_check_gate_stage0_passes_on_nonempty_counters():
    rows = _mixed_rows()
    counters = {"steps": 12, "tactics": {}}
    gate = stage_gate.check_gate("stage0", rows, counters)
    assert gate["pass"] is True
    assert {c["name"] for c in gate["checks"]} == {"min_fights", "counters_nonempty"}


def test_check_gate_stage0_fails_on_empty_counters():
    gate = stage_gate.check_gate("stage0", _mixed_rows(), {"steps": 0, "tactics": {}})
    assert gate["pass"] is False


def test_check_gate_follow_rate_na_is_fail():
    """follow_rate=None (applicable<min_support) — дефект гейта, не 0%: gate обязан упасть (§11.3)."""
    rows = _mixed_rows()
    counters = {"steps": 100, "tactics": {"no_idle": {"follow_rate": None, "applicable": 0}}}
    thresholds = {"min_fights": 1, "follow_rate_min": {"no_idle": 0.90}}
    gate = stage_gate.check_gate("stage1x", rows, counters, thresholds=thresholds)
    fr_check = next(c for c in gate["checks"] if c["name"] == "follow_rate(no_idle)")
    assert fr_check["ok"] is False and gate["pass"] is False


def test_check_gate_stage1_numbers():
    """Зелёный stage1: parity≤0.1, win≥0.3 из 30+ боёв, no_idle follow_rate 0.95."""
    rows = _mixed_rows(win_hero=12, loss_hero=3, win_foes=12, loss_foes=3)   # 30 боёв, parity 0
    counters = {"steps": 500, "tactics": {"no_idle": {"follow_rate": 0.95, "applicable": 400}}}
    gate = stage_gate.check_gate("stage1", rows, counters)
    assert gate["n_fights"] == 30
    assert gate["pass"] is True, gate["checks"]


# ------------------------------------------------------------------ markdown-отчёт
def test_write_gate_md(tmp_path):
    gate = stage_gate.check_gate("stage0", _mixed_rows(), {"steps": 5, "tactics": {}})
    path = str(tmp_path / "stage0_gate.md")
    out = stage_gate.write_gate_md("stage0", gate, path)
    assert out == path and os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert "# Stage Gate — stage0" in text and "PASS" in text


# ------------------------------------------------------------------ сквозной: real matchup rows
def _scene():
    a1 = make_npc("A1", 0, 0, disposition=-1, hp=30, speed=30, initiative=20)
    f1 = make_npc("F1", 50, 0, disposition=1, hp=8, speed=30, initiative=15)
    payload = make_scene_payload(npcs=[a1, f1], weapons=[make_weapon("sword", damage="1d6+2")])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


def test_harness_consumes_real_matchup_rows():
    """Настоящий matchup greedy-подобный кандидат vs random -> harness считает по его строкам."""
    rows = team_eval.matchup_sources(_Stub(), "random", [("s1", _scene()), ("s2", _scene())],
                                     replays=1, trace_limit=0)
    assert rows                                            # бои сыграны
    gate = stage_gate.check_gate("stage0", rows, {"steps": 10, "tactics": {}})
    assert gate["n_fights"] == len(rows)
    wld = stage_gate.win_loss_draw(rows)
    assert 0.0 <= wld["win"] <= 1.0 and abs(sum(wld.values()) - 1.0) < 1e-6
