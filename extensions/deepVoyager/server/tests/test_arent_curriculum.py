# tests/test_arent_curriculum.py — Фаза D / D4: куррикулум оппонентов weak->strong.
#
# План D4 был «операционным» (без кода ядра): единственный способ наращивать силу —
# цепочка прогонов поверх тёплого старта. Здесь добавляем ЧЕСТНЫЙ механизм в ядро:
# расписание стадий (start_iter -> набор оппонентов) и чистую функцию выбора активного
# набора для итерации. Код НЕ меняет прежнее поведение: пустой curriculum -> cfg.opponents.
import json

import pytest

from arent.rollout import RlConfig, curriculum_opponents, parse_curriculum


# --- parse_curriculum ------------------------------------------------------

def test_parse_curriculum_empty_is_no_curriculum():
    assert parse_curriculum("") == ()
    assert parse_curriculum("   ") == ()


def test_parse_curriculum_orders_stages_by_start_iter():
    spec = "30:battlecast,ufo_style;0:battlecast;20:battlecast,ufo_style,cdda_ranged_support"
    stages = parse_curriculum(spec)
    assert [s for s, _ in stages] == [0, 20, 30]
    assert stages[0] == (0, ("battlecast",))
    assert stages[1] == (20, ("battlecast", "ufo_style", "cdda_ranged_support"))
    assert stages[2] == (30, ("battlecast", "ufo_style"))


def test_parse_curriculum_tolerates_spaces_and_trailing_separators():
    stages = parse_curriculum("  0: battlecast , ufo_style ;; 10:greedy ; ")
    assert stages == ((0, ("battlecast", "ufo_style")), (10, ("greedy",)))


def test_parse_curriculum_rejects_malformed_stage():
    with pytest.raises(ValueError):
        parse_curriculum("notanumber:battlecast")


# --- curriculum_opponents --------------------------------------------------

def test_curriculum_opponents_no_curriculum_returns_configured_mix():
    cfg = RlConfig(opponents=("battlecast", "ufo_style"))
    assert curriculum_opponents(cfg, 1) == ("battlecast", "ufo_style")
    assert curriculum_opponents(cfg, 999) == ("battlecast", "ufo_style")


def test_curriculum_opponents_picks_stage_by_iteration():
    cfg = RlConfig(opponents=("battlecast",),
                   curriculum=((0, ("battlecast",)),
                               (20, ("battlecast", "ufo_style")),
                               (30, ("battlecast", "ufo_style", "cdda_ranged_support"))))
    assert curriculum_opponents(cfg, 0) == ("battlecast",)
    assert curriculum_opponents(cfg, 19) == ("battlecast",)
    assert curriculum_opponents(cfg, 20) == ("battlecast", "ufo_style")
    assert curriculum_opponents(cfg, 29) == ("battlecast", "ufo_style")
    assert curriculum_opponents(cfg, 30) == ("battlecast", "ufo_style", "cdda_ranged_support")
    assert curriculum_opponents(cfg, 40) == ("battlecast", "ufo_style", "cdda_ranged_support")


def test_curriculum_opponents_before_first_stage_falls_back_to_base():
    # стадия ещё не наступила -> база cfg.opponents (а не пусто, иначе rollout упадёт)
    cfg = RlConfig(opponents=("greedy",), curriculum=((10, ("battlecast",)),))
    assert curriculum_opponents(cfg, 1) == ("greedy",)
    assert curriculum_opponents(cfg, 10) == ("battlecast",)


def test_curriculum_opponents_is_pure_and_does_not_mutate_cfg():
    cfg = RlConfig(opponents=("battlecast",), curriculum=((5, ("ufo_style",)),))
    curriculum_opponents(cfg, 9)
    assert cfg.opponents == ("battlecast",)          # вход не мутируется


# --- RlConfig round-trip ---------------------------------------------------

def test_rlconfig_curriculum_survives_json_round_trip():
    cfg = RlConfig(opponents=("battlecast",),
                   curriculum=((0, ("battlecast",)), (20, ("battlecast", "ufo_style"))))
    restored = RlConfig.from_dict(json.loads(json.dumps(cfg.to_dict())))
    assert curriculum_opponents(restored, 20) == ("battlecast", "ufo_style")
    assert curriculum_opponents(restored, 10) == ("battlecast",)
