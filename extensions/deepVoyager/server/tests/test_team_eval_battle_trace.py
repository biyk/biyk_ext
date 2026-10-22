# tests/test_team_eval_battle_trace.py — человекочитаемый трейс боя для разбора проигрышей.
#
# ordinary `fight_teams` уже собирает step/actor/side/executed/dealt, но БЕЗ координат и
# расшифрованных целей — «глазками на арену» по нему нельзя. По умолчанию (rich_trace=False)
# поведение НЕ меняется (в основной веер дорогое не лезет). rich_trace=True добавляет в каждый
# шаг читаемые поля (cell_before/cell_after/board/attack), а render_battle_trace разворачивает
# строку боя в текстовый лог для просмотра.
import os

from playground import arena
from arent import scenarios, team_eval

SERVER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _duel_payload():
    """Одна асимметричная дуэль 1v1 (melee×ranged) как payload для боя двух политик."""
    name, raw, params = scenarios.generate_stage3_pool(1, 7,
                                                       pairs=(("melee", "ranged"),))[0]
    return arena.build_payload(raw, name), name


def test_rich_trace_has_readable_fields():
    payload, name = _duel_payload()
    row = team_eval.fight_teams(payload, "random", "battlecast", rounds_cap=6,
                                trace_limit=40, rich_trace=True)
    assert row["trace"], "в бою должен быть хотя бы один шаг"
    st = row["trace"][0]
    for key in ("cell_before", "cell_after", "board", "attack"):
        assert key in st, "rich_trace должен добавить поле %s" % key
    assert len(st["cell_after"]) == 2                       # клетка = (row, col)
    assert isinstance(st["board"], list) and st["board"]    # снапшот всех юнитов
    # attack: None (не атака) либо расшифрованная цель с id/оружием
    if st["executed_attack"]:
        assert st["attack"] is not None and "target" in st["attack"]


def test_plain_trace_has_no_rich_fields():
    payload, name = _duel_payload()
    row = team_eval.fight_teams(payload, "random", "battlecast", rounds_cap=6, trace_limit=10)
    assert row["trace"]
    assert "board" not in row["trace"][0], "без rich_trace дорогие поля добавлять нельзя"


def test_render_battle_trace_readable_text():
    payload, name = _duel_payload()
    row = team_eval.fight_teams(payload, "random", "battlecast", rounds_cap=6,
                                trace_limit=40, rich_trace=True)
    row["name"] = name
    text = team_eval.render_battle_trace(row)
    assert isinstance(text, str) and text.strip()
    assert name in text                                     # заголовок со сценой
    assert "исход" in text                                  # строка с итогом боя
