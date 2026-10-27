# tests/test_rich_trace_path.py — rich-трейс пишет полный маршрут шага и клетку удара.
#
# Вьюеру мало «из какой клетки в какую»: нужен список посредённых клеток (path) и
# attackCell — клетка, с которой реально нанесён удар (v3: удар из attack_cell, НЕ из
# end_cell). Инварианты дампера (team_eval.fight_teams, rich_trace=True):
#   path[0] == cell_before, path[-1] == cell_after;
#   каждый переход path — легальный одношаговый ход (Кебышев == 1);
#   при шагающем движении len(path) >= 2;
#   attackCell лежит на path и в достижимости от цели (melee: <= 1.5 клетки как в
#   attackable_v3); при отсутствии атаки attackCell is None.
# Схема 2 (план = одна клетка, ключа plan нет) остаётся БЕЗ новых полей — мягкая
# деградация парсера/вьюера на старых дампах.
import json

from arent import team_eval
from conftest import make_npc, make_scene_payload, make_weapon


def _npc(nid, col, disp, hp, ini, speed=30):
    return make_npc(nid, col * 50, 0, disposition=disp, hp=hp, speed=speed, initiative=ini)


def _cheb(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _duel_far():
    """Милишники в 8 клетках друг от друга: 1-й раунд — сближение (path>1), затем удар."""
    a1 = _npc("A1", 0, -1, 30, 20)
    f1 = _npc("F1", 8, 1, 30, 15)
    f1["weapons"] = [make_weapon("fsword", "меч", damage="1d6", sure_ft=5)]
    payload = make_scene_payload(npcs=[a1, f1],
                                 weapons=[make_weapon("sword", "меч", damage="1d6+2",
                                                      sure_ft=5)])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


def _fights():
    row = team_eval.fight_teams(_duel_far(), "battlecast", "battlecast", rounds_cap=4,
                                schema=3, rich_trace=True)
    return row["trace"]


def test_rich_trace_records_full_path():
    trace = _fights()
    with_path = [t for t in trace if "path" in t]
    assert with_path, "схема 3 + rich_trace обязана писать path посещённых клеток"
    moved = [t for t in with_path if t["cell_before"] != t["cell_after"]]
    assert moved, "на дальнем пулье обязаны быть шагающие ходы (path>=2)"
    for t in with_path:
        p = t["path"]
        assert p[0] == t["cell_before"] and p[-1] == t["cell_after"]
        if t["cell_before"] != t["cell_after"]:
            assert len(p) >= 2
        for a, b in zip(p, p[1:]):
            assert _cheb(a, b) == 1                       # каждый сегмент — реальный шаг


def test_attack_cell_on_path_and_in_reach():
    trace = _fights()
    strikes = [t for t in trace if t.get("attackCell") is not None]
    assert strikes, "за 4 раунда обязан быть хотя бы один удар"
    for t in strikes:
        assert t["executed_attack"]
        assert t["attackCell"] in [list(c) for c in t["path"]]
        target = next((e[4] for e in t["board"] if e[0] == t["attack"]["target"]), None)
        if target is not None:            # цель убита и выпала из state.units — не проверяем
            assert _cheb(t["attackCell"], target) <= 1    # melee 5ft: удар с соседней клетки


def test_no_attack_step_has_no_attack_cell():
    for t in _fights():
        if not t.get("executed_attack"):
            assert t.get("attackCell") is None


def test_schema2_rich_trace_unaffected():
    row = team_eval.fight_teams(_duel_far(), "battlecast", "battlecast", rounds_cap=3,
                                rich_trace=True)                       # схема 2 по умолчанию
    for t in row["trace"]:
        assert "path" not in t and "attackCell" not in t


#--- парсер: нативный дамп -> шаги вьюера ----------------------------------------
def _load_parser():
    import importlib.util
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    mod_path = os.path.join(here, "..", "tools", "trace_viewer", "parse_traces.py")
    spec = importlib.util.spec_from_file_location("parse_traces_path_mod", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_json_file_passes_path_fields(tmp_path):
    m = _load_parser()
    ts = {"step": 0, "actor": "A1", "side": "cand",
          "cell_before": [0, 0], "cell_after": [0, 2],
          "path": [[0, 0], [0, 1], [0, 2]], "attackCell": None,
          "attack": None, "executed_attack": False, "illegal": False, "dealt": 0.0,
          "board": [["A1", "A", 1, 30.0, [0, 2]], ["F1", "F", 1, 30.0, [0, 5]]]}
    dump = {"run": "t", "set": "winrate",
            "rows": [{"name": "s3_melee_vs_melee#0#h", "candidate": "c", "opponent": "o",
                      "outcome": "win", "steps": 1, "trace": [ts]}]}
    path = tmp_path / "traces_all_path.json"
    path.write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")
    st = m.parse_json_file(str(path))[0]["steps"][0]
    assert st["path"] == [[0, 0], [0, 1], [0, 2]] and st["attackCell"] is None
    assert st["from"] == [0, 0] and st["to"] == [0, 2]


#--- вьюер: проводка отрисовки (не молча лишить нас кривой) -----------------------
def test_viewer_wires_path_and_attack_cell():
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    html = open(os.path.join(here, "..", "tools", "trace_viewer", "viewer.html"),
                encoding="utf-8").read()
    assert "st.path" in html                      # маршрут рисуется по клеткам path
    assert "st.attackCell" in html                # вектор атаки — из клетки выстрела
