# tests/test_tactics_reestr.py — реестр тегов/штрафов единый источник имён (§2.3, §7).
#
# Проверяем, что ни одна строка тактики не «живёт» отдельно от Tag/Penalty: ключи, которыми
# описаны детекторы (§2.2), карта арен (§3) и веса в points.json (§5), — ровно множест
# реестра. Иначе enter_reach vs avoid_reach, don't_idle vs no_idle расъезжаются молча.
import json
import os

import pytest

from arent import tactics
from arent.tactics import ALL_KEYS, KIND, Penalty, Tag

# Canonical keys from teaching_plan §2.2 (table rows) + §3 (map) + §5 (points.json).
PLAN_BONUS_KEYS = {
    "focus_wounded", "kill_shot", "priority_soft", "kite_max_range", "cover_shoot",
    "stand_off_shoot",
    "break_ring", "hold_choke", "avoid_reach", "charge_from_cover", "anti_pincer",
    "no_stack", "use_high_ground", "no_idle", "retreat_low_hp", "focus_fire",
}
PLAN_PENALTY_KEYS = {
    "spread_fire", "approach_milishnik_as_archer", "shoot_from_open", "enter_reach",
    "widen_contacts", "leave_choke", "idle_turn", "melee_at_low_hp",
    "hit_boss_with_adds", "stack_close", "reach_penalty",
}


def test_tag_enum_matches_plan_bonus_table():
    assert {t.value for t in Tag} == PLAN_BONUS_KEYS


def test_penalty_enum_matches_plan_penalty_table():
    assert {p.value for t in [Penalty] for p in t} == PLAN_PENALTY_KEYS


def test_kind_signs_are_consistent():
    for t in Tag:
        assert KIND[t.value] == "bonus"
    for p in Penalty:
        assert KIND[p.value] == "penalty"


def test_no_duplicate_keys_across_bonus_and_penalty():
    assert set(tactics.BONUS_KEYS) & set(tactics.PENALTY_KEYS) == set()
    assert len(set(ALL_KEYS)) == len(ALL_KEYS)


def test_don_idle_legacy_name_is_not_used():
    # §10.2: «don't_idle» и no_idle — одно и то же; в реестре только no_idle.
    assert "no_idle" in ALL_KEYS
    assert "don't_idle" not in ALL_KEYS
    assert "dont_idle" not in ALL_KEYS


def test_points_json_tactics_keys_are_in_registry():
    """Секция tactics в points.json не имеет права ссылаться на висящее имя (§5)."""
    server = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(server, "points.json")
    if not os.path.exists(path):
        pytest.skip("points.json отсутствует")
    raw = json.load(open(path, encoding="utf-8"))
    tac = raw.get("tactics")
    if not tac:
        pytest.skip("секция tactics ещё не добавлена (этап t3)")
    for section in ("weights", "penalties"):
        for key in tac.get(section, {}):
            assert key in ALL_KEYS, f"{section}.{key} вне реестра §2.3"


def test_tactics_map_expected_strategies_are_in_registry():
    """Ни одна арена не может ждать несуществующий тег (§3)."""
    arent_dir = os.path.dirname(os.path.abspath(tactics.__file__))
    path = os.path.join(arent_dir, "tactics_map.json")
    if not os.path.exists(path):
        pytest.skip("tactics_map.json ещё не добавлен (этап t4)")
    raw = json.load(open(path, encoding="utf-8"))
    for entry in raw.values():
        if not isinstance(entry, dict):
            continue
        for key in list(entry.get("enabled", [])) + list(entry.get("penalties", [])):
            assert key in ALL_KEYS, f"{key} вне реестра §2.3"
