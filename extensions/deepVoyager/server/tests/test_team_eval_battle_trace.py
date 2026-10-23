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
from arent import tactics_config
from arent.tactics_counters import Counters

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


def test_rich_trace_has_reward_breakdown():
    # «какие награды получает модель за свои действия» — разложение награды шага в трейсе.
    payload, name = _duel_payload()
    row = team_eval.fight_teams(payload, "random", "battlecast", rounds_cap=6,
                                trace_limit=40, rich_trace=True)
    st = row["trace"][0]
    assert "reward" in st and "reward_breakdown" in st
    assert set(st["reward_breakdown"]) >= {"base", "potential", "tactical_applied"}


def test_shape_stage_filters_asif_tags():
    # as-if теги в трейсе должны уважать stage-отключение: stage3 не отдаёт запрещённые теги.
    payload, name = _duel_payload()
    counters = Counters()
    row = team_eval.fight_teams(payload, "random", "battlecast", rounds_cap=6, trace_limit=60,
                                rich_trace=True, counters=counters, shape_stage="stage3")
    allowed3 = set(tactics_config.config().allowed("stage3"))
    seen = set()
    for st in row["trace"]:
        tags = (st.get("reward_breakdown") or {}).get("tags") or {}
        seen |= set(tags.get("fired", [])) | set(tags.get("violated", []))
    assert seen <= allowed3, "stage3-asif не должен отдавать отключённые на stage3 теги"


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
    assert "награда" in text                                # разложение награды шага в логе
