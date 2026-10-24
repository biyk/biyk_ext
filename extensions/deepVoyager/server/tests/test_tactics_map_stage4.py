# tests/test_tactics_map_stage4.py — гейт арен Этапа 4: укрытия и узости (§3, §4, §7).
#
# infer_strategies обязан включать cover_shoot при наличии стен (уже так) И hold_choke/leave_choke
# при has_choke (арена с артикуляционной клеткой графа проходимости). Без узости — не включать.
from arent import tactics_map as tm


def _params(**over):
    base = {"archetype": "duel", "side_a_classes": ["ranged"], "side_b_classes": ["melee"],
            "n_walls": 0, "n_allies": 1, "has_choke": False}
    return {**base, **over}


def test_walls_enable_cover_shoot():
    exp = tm.infer_strategies(_params(n_walls=4))
    assert "cover_shoot" in exp["enabled"]
    assert "shoot_from_open" in exp["penalties"]


def test_no_walls_does_not_enable_cover_shoot():
    exp = tm.infer_strategies(_params(n_walls=0))
    assert "cover_shoot" not in exp["enabled"]


def test_has_choke_enables_hold_choke_and_leave_penalty():
    exp = tm.infer_strategies(_params(has_choke=True))
    assert "hold_choke" in exp["enabled"]
    assert "leave_choke" in exp["penalties"]


def test_absent_choke_does_not_enable_hold_choke():
    exp = tm.infer_strategies(_params(has_choke=False))
    assert "hold_choke" not in exp["enabled"]
    assert "leave_choke" not in exp["penalties"]


def test_missing_has_choke_key_is_safe():
    # старый params без ключа has_choke не должен ронять вывод и не даёт hold_choke
    params = {"archetype": "duel", "side_a_classes": ["ranged"], "side_b_classes": ["melee"],
              "n_walls": 2, "n_allies": 1}
    exp = tm.infer_strategies(params)
    assert "hold_choke" not in exp["enabled"]
    assert "cover_shoot" in exp["enabled"]
