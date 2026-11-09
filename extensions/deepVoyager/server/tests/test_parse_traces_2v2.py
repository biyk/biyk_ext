# tests/test_parse_traces_2v2.py — дампы Этапа 4.1 (симм. 2v2) во вьюере.
#
# units строится по board-uid, а не жёстко A1/F1: в 2v2 во вьюере четыре бойца
# (A1,A2 — герои; F1,F2 — враги), у каждого свой hpMax из максимума по трейсу;
# cls известен только базовым A1/F1 (из имени боя), у A2/F2 — None (нет иконки).
# gear (клик по бойцу) обязан покрывать всех четырёх, а не только базовую пару.
import json
import os


def _load_parser():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    mod_path = os.path.join(here, "..", "tools", "trace_viewer", "parse_traces.py")
    spec = importlib.util.spec_from_file_location("parse_traces_2v2_mod", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dump2v2():
    def ts(step, actor, side, before, after, board, weapon=None):
        return {"step": step, "actor": actor, "side": side,
                "cell_before": before, "cell_after": after,
                "attack": ({"target": "F1", "weapon": weapon} if weapon else None),
                "executed_attack": bool(weapon), "illegal": False,
                "dealt": 3.5 if weapon else 0.0, "board": board}

    tokens = [{"id": uid, "name": nm, "hp": hp, "weapons": [{"id": "sword", "name": "Меч"}]}
              for uid, nm, hp in (("A1", "melee-1", 7), ("A2", "tank-2", 30),
                                  ("F1", "melee-1", 12), ("F2", "tank-2", 10))]
    return {"run": "s41es", "set": "winrate",
            "rows": [{
                "name": "s41_meleevtank_000", "battle_uid": "two2two000",
                "candidate": "s41es", "opponent": "greedy",
                "outcome": "win", "steps": 2, "rounds": 0,
                "arena": {"tokens": tokens},
                "trace": [
                    ts(0, "A2", "cand", [3, 3], [3, 4],
                       [["A1", "A", 1, 7.0, [1, 1]], ["A2", "A", 1, 30.0, [3, 4]],
                        ["F1", "F", 1, 12.0, [8, 8]], ["F2", "F", 1, 10.0, [9, 9]]],
                       weapon="Меч"),
                    ts(1, "F2", "opp", [9, 9], [9, 8],
                       [["A1", "A", 1, 7.0, [1, 1]], ["A2", "A", 1, 26.5, [3, 4]],
                        ["F1", "F", 1, 12.0, [8, 8]], ["F2", "F", 1, 10.0, [9, 8]]]),
                ]}]}


def test_4_units_with_hp_and_sides(tmp_path):
    m = _load_parser()
    p = tmp_path / "traces_win_2v2.json"
    p.write_text(json.dumps(_dump2v2(), ensure_ascii=False), encoding="utf-8")
    b = m.parse_json_file(str(p))[0]
    u = b["units"]
    assert set(u) == {"A1", "A2", "F1", "F2"}, "в 2v2 вьюер должен видеть всех четырёх"
    assert u["A2"]["side"] == "hero" and u["F2"]["side"] == "foe"
    assert u["A2"]["hpMax"] == 30.0                   # максимум по трейсу, не текущее hp
    assert u["A2"]["cls"] is None and u["F2"]["cls"] is None   # класс есть только у A1/F1
    assert u["A1"]["cls"] == "melee" and u["F1"]["cls"] == "tank"   # базовая пара из имени
    assert b["set"] == "winrate" and b["rounds"] == 0
    assert b["steps"][0]["weapon"] == "Меч"


def test_gear_covers_every_fighter(tmp_path):
    m = _load_parser()
    p = tmp_path / "traces_win_2v2_gear.json"
    p.write_text(json.dumps(_dump2v2(), ensure_ascii=False), encoding="utf-8")
    b = m.parse_json_file(str(p))[0]
    assert set(b["gear"]) == {"A1", "A2", "F1", "F2"}
    assert b["gear"]["A2"]["weapons"][0]["name"] == "Меч"
