# tests/test_tactics_map.py — карта архетипов и вывод ожидаемых тактик из состава (§3, §7).
#
# Проверяем: у каждого архетипа scenario_units есть запись в карте; infer_strategies добавляет
# ситуативные теги по составу/стенам; allowed_set не пропускает висящих имён; явный манифест
# арены (declared) важнее вывода. Это фундамент arena-gate: бонус только там, где применимо.
from arent import tactics_map as tm
from arent.scenario_units import ARCHETYPES
from arent.tactics import ALL_KEYS


def test_every_archetype_has_a_map_entry():
    for arch in ARCHETYPES:
        assert arch in tm.ARCH_MAP, f"архетип {arch} не описан в tactics_map.json"


def test_map_keys_are_in_registry():
    for entry in tm.ARCH_MAP.values():
        for key in entry["enabled"] + entry["penalties"]:
            assert key in ALL_KEYS


def test_infer_adds_kite_for_archer_vs_melee():
    params = {"archetype": "duel", "side_a_classes": ["ranged"], "side_b_classes": ["melee"],
              "n_walls": 0, "n_allies": 1}
    exp = tm.infer_strategies(params)
    assert "kite_max_range" in exp["enabled"]
    assert "approach_milishnik_as_archer" in exp["penalties"]


def test_infer_adds_focus_fire_when_multi_ally():
    params = {"archetype": "duel", "side_a_classes": ["melee"], "side_b_classes": ["melee"],
              "n_walls": 0, "n_allies": 2}
    exp = tm.infer_strategies(params)
    assert "focus_fire" in exp["enabled"]
    assert "spread_fire" in exp["penalties"]


def test_infer_adds_avoid_reach_against_reach_enemy():
    params = {"archetype": "duel", "side_a_classes": ["melee"], "side_b_classes": ["reach"],
              "n_walls": 0, "n_allies": 1}
    exp = tm.infer_strategies(params)
    assert "avoid_reach" in exp["enabled"]
    assert "enter_reach" in exp["penalties"]


def test_expected_keys_prefers_declared_manifest():
    params = {"archetype": "duel", "side_a_classes": ["melee"], "side_b_classes": ["melee"]}
    declared = {"enabled": ["kill_shot"], "penalties": ["idle_turn"]}
    assert tm.expected_keys(params, declared) == declared


def test_allowed_set_drops_unknown_names():
    exp = {"enabled": ["kill_shot", "ghost_tag"], "penalties": ["idle_turn"]}
    assert tm.allowed_set(exp) == {"kill_shot", "idle_turn"}
