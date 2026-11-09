# tests/test_arent_gate.py — Фаза D / D3: честный гейт против МИКСА учителей (чистая функция).
#
# Прежний гейт stage5 мерил только «vs battlecast». План D3: модель обязана пройти против
# КАЖДОГО учителя микса — не регрессить ни к одному (win_rate>=порог И bootstrap-нижняя
# граница>=порог на достаточном числе боёв). Вынесено в arent/gate.py как ЧИСТАЯ функция,
# чтобы вердикт тестировался без Ray/обучения (пайплайн лишь вызывает его на своих agg-мерах).
import pytest

from arent.gate import gate_verdict


def _m(win, boot, fights):
    return {"win_rate": win, "boot_lower": boot, "fights": fights}


def test_gate_verdict_passes_when_all_teachers_beaten():
    metrics = {"battlecast": _m(0.60, 0.52, 40), "ufo_style": _m(0.55, 0.51, 40),
               "cdda_ranged_support": _m(0.70, 0.60, 40)}
    v = gate_verdict(metrics, win_thr=0.50, boot_thr=0.50, min_fights=30)
    assert v["passed"] is True
    assert v["worst_win_rate"] == pytest.approx(0.55)
    assert v["failed"] == []


def test_gate_verdict_fails_if_any_single_teacher_is_not_beaten():
    metrics = {"battlecast": _m(0.60, 0.52, 40), "ufo_style": _m(0.48, 0.44, 40)}
    v = gate_verdict(metrics, win_thr=0.50, boot_thr=0.50, min_fights=30)
    assert v["passed"] is False
    assert "ufo_style" in v["failed"]
    assert "battlecast" in v["per_teacher"] and v["per_teacher"]["battlecast"]["passed"]


def test_gate_verdict_requires_bootstrap_lower_bound_not_just_mean():
    # среднее 0.55 >= 0.50, но нижняя CI 0.47 < 0.50 -> не засчитываем (шум, не перевес)
    metrics = {"battlecast": _m(0.55, 0.47, 40)}
    v = gate_verdict(metrics, win_thr=0.50, boot_thr=0.50, min_fights=30)
    assert v["passed"] is False
    assert v["failed"] == ["battlecast"]


def test_gate_verdict_flags_insufficient_fights_as_not_passed():
    metrics = {"battlecast": _m(0.90, 0.85, 12)}       # переиграл, но бойов меньше минимума
    v = gate_verdict(metrics, win_thr=0.50, boot_thr=0.50, min_fights=30)
    assert v["passed"] is False
    assert v["insufficient"] == ["battlecast"]


def test_gate_verdict_empty_metrics_is_not_a_pass():
    """Нельзя «сертифицировать» модель на пустом наборе соперников — это не PASS."""
    v = gate_verdict({}, win_thr=0.50, boot_thr=0.50, min_fights=30)
    assert v["passed"] is False
    assert v["teachers"] == []


def test_gate_verdict_is_deterministic_and_pure():
    metrics = {"b": _m(0.6, 0.55, 40), "a": _m(0.6, 0.55, 40)}
    first = gate_verdict(metrics, win_thr=0.50, boot_thr=0.50, min_fights=30)
    second = gate_verdict(metrics, win_thr=0.50, boot_thr=0.50, min_fights=30)
    assert first == second                            # без побочки, один вход -> один выход
    assert metrics["a"]["win_rate"] == 0.6            # вход не мутируется
