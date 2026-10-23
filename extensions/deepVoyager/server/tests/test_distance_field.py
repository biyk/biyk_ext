# tests/test_distance_field.py — непрерывная дистанционная шкала для дальнобойного (переразметка).
#
# Идея пользователя: форма награды по нормированной дистанции r = dist / R_conf (R_conf = reach
# оружия = дистанция уверенной атаки):
#   • r < near_cut(0.3)  -> ШТРАФ (враг вплотную, point-blank опасно);
#   • near_cut..peak(1.0)-> награда РАСТЁТ к максимуму у уверенной дистанции;
#   • peak..far_cut(2.0)-> плавно СПАДАЕТ к 0 (за пределами уверенного выстрела — далеко/бесполезно);
#   • r > far_cut       -> 0.
# Только для ranged-актёра и только когда есть melee-угроза (иначе нейтрально 0). Значение
# непрерывное, поэтому не является тегом-детектором: считается отдельной функцией и подмешивается
# в shaping (train-only, record_only по-прежнему возвращает 0 в награду).
import pytest

from arent.tactics import StepCtx, UnitView
from arent.tactics_config import DistanceField, parse
from arent.tactics_counters import Counters
from arent.tactics_detect import distance_field_value
from arent.tactics_shaper import TacticsShaper

DF = DistanceField(enabled=True, amp=0.12, near_cut=0.30, peak=1.0, far_cut=2.0)
R_CONF = 10.0


def _ctx(dist, ranged_actor=True, attacked=True):
    # attacked=True по умолчанию: поле — морковка ЗА УДЕРЖАНИЕ дистанции ПОД ВЫСТРЕЛОМ.
    # Без атаки дальнобойный не должен получать + за то, что просто отбежал (см. ниже).
    actor = UnitView(id="me", cell=(0, 0), hp=20, hp_max=20, alive=True, reach=R_CONF,
                     ranged=ranged_actor, role="ranged" if ranged_actor else "melee")
    foe = UnitView(id="F1", cell=(0, dist), hp=10, hp_max=10, alive=True, reach=1.0,
                   ranged=False, role="melee")
    return StepCtx(actor=actor, cell_after=(0, 0), foes=(foe,), attacked=attacked)


def test_field_penalty_when_too_close():
    assert distance_field_value(_ctx(1), DF) == pytest.approx(-0.08, abs=1e-6)   # r=0.1 -> -amp*(0.3-0.1)/0.3


def test_field_zero_at_near_cut():
    assert distance_field_value(_ctx(3), DF) == pytest.approx(0.0, abs=1e-6)     # r=0.3


def test_field_peak_at_confident_range():
    assert distance_field_value(_ctx(10), DF) == pytest.approx(0.12, abs=1e-6)   # r=1.0


def test_field_half_on_far_side():
    assert distance_field_value(_ctx(15), DF) == pytest.approx(0.06, abs=1e-6)   # r=1.5


def test_field_zero_beyond_far_cut():
    assert distance_field_value(_ctx(30), DF) == 0.0                             # r=3.0


def test_field_zero_for_melee_actor():
    assert distance_field_value(_ctx(10, ranged_actor=False), DF) == 0.0


def test_field_zero_when_no_melee_threat():
    actor = UnitView(id="me", cell=(0, 0), hp=20, hp_max=20, alive=True, reach=R_CONF,
                     ranged=True, role="ranged")
    foe = UnitView(id="F1", cell=(0, 10), hp=10, hp_max=10, alive=True, reach=6.0,
                   ranged=True, role="ranged")          # только дальный враг -> нет melee-угрозы
    assert distance_field_value(StepCtx(actor=actor, cell_after=(0, 0), foes=(foe,)), DF) == 0.0


def test_field_disabled_returns_zero():
    assert distance_field_value(_ctx(10), DistanceField(enabled=False, amp=0.12)) == 0.0


def test_field_positive_requires_attack():
    # §Закрыть вредную награду: без атаки ПОЛОЖИТЕЛЬНАЯ морковка поля не платится — иначе
    # политика получает + за беготню от melee-угрозы без единого выстрела (вредное поведение).
    assert distance_field_value(_ctx(10, attacked=False), DF) == 0.0


def test_field_keeps_penalty_without_attack():
    # Штраф за опасность (вплотную к melee) остаётся и без атаки: он не раздувает награду,
    # а наоборот наказывает неправильное стояние — обрезаем только положительную часть.
    assert distance_field_value(_ctx(1, attacked=False), DF) == pytest.approx(-0.08, abs=1e-6)


# ------------------------------------------------------------------ шейпер: поле вливается в shaping
_DF_CFG = {"weights": {}, "distance_field": {"enabled": True, "amp": 0.12, "near_cut": 0.3,
                                             "peak": 1.0, "far_cut": 2.0}}


def test_shaper_train_addend_includes_field():
    cfg = parse(_DF_CFG)
    shaper = TacticsShaper(cfg, cfg.allowed(), Counters(), record_only=False)
    shaper.anneal(0, 1)                                   # λ=1
    assert shaper.addend(_ctx(10)) == pytest.approx(0.12, abs=1e-6)
    assert shaper.last_diag["field"] == pytest.approx(0.12, abs=1e-6)


def test_shaper_record_only_returns_zero_but_stashes_field():
    cfg = parse(_DF_CFG)
    shaper = TacticsShaper(cfg, cfg.allowed(), Counters(), record_only=True)
    shaper.anneal(0, 1)
    assert shaper.addend(_ctx(10)) == 0.0                 # в награду eval не течёт (§1.1)
    assert shaper.last_diag["field"] == pytest.approx(0.12, abs=1e-6)   # но видно в трейсе


def test_shaper_train_no_positive_reward_for_non_attack():
    # §Главное требование пользователя: неправильное поведение НЕ должно увеличивать награду.
    # Дальнобойный, отбежавший на уверенную дистанцию, но НЕ выстреливший, в train получает 0
    # тактического члена (ни addend, ни as-if) — морковка привязана к атаке.
    cfg = parse(_DF_CFG)
    shaper = TacticsShaper(cfg, cfg.allowed(), Counters(), record_only=False)
    shaper.anneal(0, 1)
    assert shaper.addend(_ctx(10, attacked=False)) == 0.0
    assert shaper.last_diag["asif"] <= 0.0
