# tests/test_tactics_config.py — загрузка/валидация секции tactics из points.json (§5, §7).
#
# Проверяем: нет секции -> shaping выключен; опечатка в ключе -> ValueError (не нулевой вес);
# linear-decay даёт λ(0)=1, λ(total)=floor; allowed(stage) снимает per_stage_disable; и что
# КОМПЛИМЕНТ в points.json действительно парсится и держит ключи реестра.
import os

import pytest

from arent.tactics import Penalty, Tag
from arent.tactics_config import parse, from_file

SERVER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_missing_section_disables_shaping():
    cfg = parse(None)
    assert cfg.enabled_global is False
    assert cfg.weights == {} and cfg.penalties == {}


def test_unknown_weight_key_raises():
    with pytest.raises(ValueError):
        parse({"weights": {"not_a_tag": 0.1}})


def test_unknown_penalty_key_raises():
    with pytest.raises(ValueError):
        parse({"penalties": {"not_a_penalty": -0.1}})


def test_linear_decay_lambda():
    cfg = parse({"decay": {"mode": "linear", "floor": 0.0}})
    assert cfg.lam(0, 60) == pytest.approx(1.0)
    assert cfg.lam(30, 60) == pytest.approx(0.5)
    assert cfg.lam(60, 60) == pytest.approx(0.0)


def test_allowed_removes_stage_disabled():
    cfg = parse({
        "weights": {Tag.no_idle.value: 0.03, Tag.cover_shoot.value: 0.15},
        "penalties": {Penalty.idle_turn.value: -0.05},
        "per_stage_disable": {"stage1": [Tag.cover_shoot.value]},
    })
    assert Tag.cover_shoot.value in cfg.allowed()
    assert Tag.cover_shoot.value not in cfg.allowed("stage1")
    assert Tag.no_idle.value in cfg.allowed("stage1")


def test_shipped_points_json_parses_and_uses_registry_keys():
    cfg = from_file(os.path.join(SERVER, "points.json"))
    assert cfg.enabled_global is True
    assert cfg.cap_of_win == pytest.approx(0.3)
    assert cfg.weights[Tag.focus_wounded.value] == pytest.approx(0.10)
    assert cfg.penalties[Penalty.enter_reach.value] == pytest.approx(-0.12)


def test_from_file_missing_returns_disabled():
    cfg = from_file(os.path.join(SERVER, "does_not_exist_points.json"))
    assert cfg.enabled_global is False


def test_stage2_enables_kiting_and_reach_but_not_multitarget():
    # §Этап 2: тактики = stage1 + kite_max_range (avoid_reach и так не гаснет на stage1);
    # многоцели/рельеф (focus_fire, cover_shoot) остаются выключены до более поздних этапов.
    cfg = from_file(os.path.join(SERVER, "points.json"))
    s1 = cfg.allowed("stage1")
    s2 = cfg.allowed("stage2")
    assert Tag.kite_max_range.value not in s1        # на Этапе 1 кайт запрещён
    assert Tag.kite_max_range.value in s2            # на Этапе 2 включился
    assert Tag.avoid_reach.value in s2
    assert Tag.cover_shoot.value not in s2 and Tag.focus_fire.value not in s2
    assert Tag.focus_wounded.value in s2 and Tag.kill_shot.value in s2
