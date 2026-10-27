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


def test_distance_field_defaults_disabled():
    # без блока distance_field поле выключено -> обратная совместимость (в shaping не лезет).
    cfg = parse({"weights": {}})
    assert cfg.distance_field.enabled is False


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


def test_shipped_distance_field_and_upweighted_ranged_carrots():
    # §Текущие данные: непрерывная дистанционная шкала ВЫКЛЮЧЕНА (убрана как лишняя), но
    # морковки дальнего боя усилены и остаются в наборе.
    cfg = from_file(os.path.join(SERVER, "points.json"))
    assert cfg.distance_field.enabled is False
    assert cfg.weights[Tag.stand_off_shoot.value] == pytest.approx(0.05)
    assert cfg.weights[Tag.kite_max_range.value] == pytest.approx(0.15)


def test_from_file_missing_returns_disabled():
    cfg = from_file(os.path.join(SERVER, "does_not_exist_points.json"))
    assert cfg.enabled_global is False


def test_shipped_shaping_disabled_in_favor_of_damage_reward():
    # §Пивот наград v3: тактический shaping (теги/штрафы) ВЫКЛЮЧЕН — награда теперь чисто по
    # величине урона (TeamReward base: damage_dealt/damage_taken + win/kill). Все tactic-теги
    # сняты enabled:false, поэтому allowed() пуст на всех этапах; числа weights/penalties в
    # реестре остались лишь как справка (в награду не текут).
    cfg = from_file(os.path.join(SERVER, "points.json"))
    assert cfg.penalties[Penalty.ranged_grabbed.value] == pytest.approx(-0.25)  # вес цел в реестре
    assert Penalty.ranged_grabbed.value in cfg.disabled                          # но снят флагом
    assert cfg.allowed("stage3") == set() and cfg.allowed("stage2") == set()


def test_shipped_hard_block_parses_but_inactive():
    # §Неугасающее ядро остаётся декларированным (на будущее, когда shaping вернут): hard-ключи
    # валидны по реестру, но при enabled:false-тегах в allowed() не попадают (они в disabled).
    cfg = from_file(os.path.join(SERVER, "points.json"))
    assert cfg.hard == frozenset({"ranged_grabbed", "kite_max_range",
                                  "stand_off_shoot", "avoid_reach"})
    for k in cfg.hard:
        assert k in cfg.disabled and k not in cfg.allowed("stage3")


def test_parse_hard_unknown_key_raises():
    with pytest.raises(ValueError):
        parse({"weights": {}, "penalties": {}, "hard": ["not_a_tag"]})


def test_parse_hard_defaults_empty():
    # без блока hard -> ничего не exempt, обратная совместимость (весь shaping под λ/cap).
    cfg = parse({"weights": {Tag.no_idle.value: 0.03}})
    assert cfg.hard == frozenset()


#--- единое место управления: базовые события (base) и флаг вкл/выкл тега ---- #
def test_parse_base_values_and_disabled_to_zero():
    # base принимает {value,enabled} или голое число; enabled=False -> эффективный 0 (вклад гаснет).
    cfg = parse({"weights": {}, "base": {"win": {"value": 6.0, "enabled": True},
                                           "kill": {"value": 0.5, "enabled": False}}})
    assert cfg.base["win"] == pytest.approx(6.0)
    assert cfg.base["kill"] == pytest.approx(0.0)          # выключен -> 0


def test_parse_base_plain_number_without_wrapper():
    cfg = parse({"weights": {}, "base": {"loss": -9.0}})
    assert cfg.base["loss"] == pytest.approx(-9.0)


def test_tags_enabled_false_excludes_globally_from_allowed():
    cfg = parse({"weights": {Tag.no_idle.value: 0.03, Tag.cover_shoot.value: 0.15},
                 "penalties": {}, "tags": {Tag.cover_shoot.value: {"enabled": False}}})
    assert cfg.disabled == frozenset({Tag.cover_shoot.value})
    assert Tag.cover_shoot.value not in cfg.allowed()       # снят по флагу на всех этапах
    assert Tag.no_idle.value in cfg.allowed()


def test_shipped_points_json_base_and_tags():
    cfg = from_file(os.path.join(SERVER, "points.json"))
    # §Новая база v3: победа абсолютна, убийство побочно, поражение/ничья = 0, урон по величине.
    assert cfg.base.get("win") == pytest.approx(50.0)
    assert cfg.base.get("kill") == pytest.approx(5.0)
    assert cfg.base.get("loss") == pytest.approx(0.0)
    assert cfg.base.get("damage_dealt") == pytest.approx(1.0)
    assert cfg.base.get("damage_taken") == pytest.approx(0.9)
    assert cfg.base.get("hit") == pytest.approx(0.0)            # устарело -> enabled:false -> 0
    assert cfg.base.get("living_cost") == pytest.approx(0.0)    # устарело -> enabled:false -> 0
    # shaping выключен: ВСЕ тактические теги сняты enabled:false -> allowed() пуст на всех этапах.
    assert cfg.allowed("stage3") == set()


def test_stage_gating_logic_preserved_in_shipped_config():
    # §Логика поэтапного отключения (per_stage_disable) сохранена в points.json. Сейчас весь
    # shaping погашен флагом enabled:false на всех тегах -> allowed() пуст. Проверяем, что
    # расписание этапов целое (при возврате shaping тег подчинится прежнему графику).
    cfg = from_file(os.path.join(SERVER, "points.json"))
    assert cfg.allowed("stage2") == set() and cfg.allowed("stage3") == set()   # shipped: всё выкл.
    assert Tag.kite_max_range.value in cfg.per_stage_disable.get("stage1", ())
    assert Tag.cover_shoot.value in cfg.per_stage_disable.get("stage2", ())
    assert Tag.priority_soft.value in cfg.per_stage_disable.get("stage2", ())


def test_stage_disable_schedule_holds_when_tags_reenabled():
    # §Синтетика (не shipped-файл): если теги включить, прежнее расписание этапов работает —
    # kite на stage2, priority/retreat на stage3, рельеф/мультицепь вне раннего набора.
    tags = {t.value: {"enabled": True} for t in
            (Tag.kite_max_range, Tag.avoid_reach, Tag.no_idle, Tag.cover_shoot,
             Tag.focus_fire, Tag.priority_soft, Tag.retreat_low_hp)}
    w = {t.value: 0.1 for t in (Tag.kite_max_range, Tag.avoid_reach, Tag.no_idle,
                               Tag.cover_shoot, Tag.focus_fire, Tag.priority_soft,
                               Tag.retreat_low_hp)}
    base = from_file(os.path.join(SERVER, "points.json")).per_stage_disable
    cfg = parse({"weights": w, "penalties": {}, "tags": tags, "per_stage_disable": base})
    s1, s2, s3 = cfg.allowed("stage1"), cfg.allowed("stage2"), cfg.allowed("stage3")
    assert Tag.kite_max_range.value not in s1 and Tag.kite_max_range.value in s2
    assert Tag.priority_soft.value not in s2 and Tag.priority_soft.value in s3
    assert Tag.retreat_low_hp.value in s3
    assert Tag.cover_shoot.value not in s3 and Tag.focus_fire.value not in s3
