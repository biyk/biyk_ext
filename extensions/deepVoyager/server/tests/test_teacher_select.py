# tests/test_teacher_select.py — выбор сильнейшего учителя в роли (для DAgger-разметки).
#
# §Выбор пользователя: «берём тактики сильнейшего в данной роли». Честный замер
# (.ray/measure_role_teacher.py, greedy vs battlecast на всём stage3-пуле, обе расстановки)
# показал: battlecast не хуже greedy НИ В ОДНОЙ роли и обычно лучше (melee 35>23, ranged 71>63,
# tank 48=48). Значит по текущим данным «сильнейший в роли» = battlecast для всех ролей. Механизм
# оставляем табличным и расширяемым: если будущий замер разведёт роли — правим таблицу, не код.
from arent.teacher_select import (DEFAULT_ROLE_TEACHER, derive_role, measured_table,
                                  teacher_for_role)


def test_default_table_is_battlecast_everywhere_by_measurement():
    # зафиксированный итог замера: производная роль -> сильнейший учитель.
    assert DEFAULT_ROLE_TEACHER == {"ranged": "battlecast", "melee": "battlecast",
                                    "tank": "battlecast"}


def test_teacher_for_known_and_unknown_role():
    assert teacher_for_role("ranged") == "battlecast"
    assert teacher_for_role("melee") == "battlecast"
    assert teacher_for_role("tank") == "battlecast"
    assert teacher_for_role("no_such_role") == "battlecast"      # fallback = сильнейший в целом


def test_selector_is_pluggable_per_table():
    # таблица вляется: если замер разведёт роли — selector вернётdifferent учителя по роли.
    table = {"ranged": "greedy", "melee": "battlecast"}
    assert teacher_for_role("ranged", table) == "greedy"
    assert teacher_for_role("melee", table) == "battlecast"


def test_derive_role_matches_tactics_ctx_heuristics():
    # дальнобойность по reach>=3, «танк» по hp>=24 (совпадает с tactics_ctx._derive_role).
    assert derive_role(reach_cells=6.0, hp_max=20.0) == "ranged"
    assert derive_role(reach_cells=1.0, hp_max=30.0) == "tank"
    assert derive_role(reach_cells=1.0, hp_max=10.0) == "melee"


def test_measured_table_returns_per_role_mapping():
    # измеритель возвращает mapping роль->учитель и умеет разводить роли при доминировании.
    tally = {"ranged": {"greedy": 1, "battlecast": 9}, "melee": {"greedy": 8, "battlecast": 2}}
    table = measured_table(tally)
    assert table["ranged"] == "battlecast"
    assert table["melee"] == "greedy"
