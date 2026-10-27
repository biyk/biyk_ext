# tests/test_parse_traces_obs.py — парсер выкладывает obs_input sidecar-файлами obs/.
#
# Дамп с obs_input (team_eval obs_trace="cand"/"all") -> parse_json_file:
#   каждый шаг ИМЕЮЩИЙ obs_input получает файл obs/<battle_uid>_step<N>.json (UTF-8);
#   в step вьюера — поле obsFile (путь с «/»), а САМ obs_input в battles НЕ попадает
#   (не раздувать battles.js); какой шаг получает obs_input решает дампер (cand/all);
#   дамп без obs_input — ни файлов, ни поля (обратная совместимость со старыми дампами);
#   перед записью боя его старые sidecar-файлы obs/<uid>_step*.json удаляются
#   (защита от stale-шагов перегенерированного дампа).
import json
import os


def _load_parser():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    mod_path = os.path.join(here, "..", "tools", "trace_viewer", "parse_traces.py")
    spec = importlib.util.spec_from_file_location("parse_traces_obs_mod", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dump(with_obs):
    ts_cand = {"step": 0, "actor": "A1", "side": "cand",
               "cell_before": [0, 0], "cell_after": [0, 1],
               "attack": None, "executed_attack": False, "illegal": False, "dealt": 0.0,
               "board": [["A1", "A", 1, 30.0, [0, 1]], ["F1", "F", 1, 30.0, [0, 5]]]}
    ts_opp = {"step": 1, "actor": "F1", "side": "opp",
              "cell_before": [0, 5], "cell_after": [0, 4],
              "attack": None, "executed_attack": False, "illegal": False, "dealt": 0.0,
              "board": [["A1", "A", 1, 30.0, [0, 1]], ["F1", "F", 1, 30.0, [0, 4]]]}
    if with_obs:
        ts_cand["obs_input"] = {"legal": [[0, 0, 0]], "cells": [1.0, 0.0], "actor": "A1"}
        # шаг соперника без obs_input — как при obs_trace="cand" (дампер сам фильтровал)
    return {"run": "t", "set": "chaos", "obs": "cand",
            "rows": [{"name": "s3_duel#0#h", "battle_uid": "abc123def0",
                      "candidate": "c", "opponent": "o",
                      "outcome": "win", "steps": 2, "trace": [ts_cand, ts_opp]}]}


def _write_dump(tmp_path, with_obs):
    p = tmp_path / "traces_all_obs.json"
    p.write_text(json.dumps(_dump(with_obs), ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_sidecar_written_and_not_embedded(tmp_path):
    m = _load_parser()
    obs_dir = tmp_path / "obs"
    battles = m.parse_json_file(_write_dump(tmp_path, True), obs_dir=str(obs_dir))
    st0, st1 = battles[0]["steps"][0], battles[0]["steps"][1]
    assert st0["obsFile"] == "obs/abc123def0_step0.json"
    assert "obsFile" not in st1                       # шага без obs_input нет и в вьюере
    f = obs_dir / "abc123def0_step0.json"
    assert f.exists()
    got = json.loads(f.read_text(encoding="utf-8"))
    assert got == {"legal": [[0, 0, 0]], "cells": [1.0, 0.0], "actor": "A1"}
    blob = json.dumps(battles)                        # в battles.js obs НЕ тащим
    assert "obs_input" not in blob and "[1.0, 0.0]" not in blob


def test_legacy_dump_no_obs_no_sidecar(tmp_path):
    m = _load_parser()
    obs_dir = tmp_path / "obs"
    battles = m.parse_json_file(_write_dump(tmp_path, False), obs_dir=str(obs_dir))
    for st in battles[0]["steps"]:
        assert "obsFile" not in st and "obs_input" not in st


def test_stale_sidecars_of_same_battle_are_dropped(tmp_path):
    m = _load_parser()
    obs_dir = tmp_path / "obs"
    obs_dir.mkdir()
    stale = obs_dir / "abc123def0_step9.json"
    stale.write_text("{}", encoding="utf-8")           # шаг от прежней генерации этого же боя
    other = obs_dir / "otheruid_step0.json"
    other.write_text("{}", encoding="utf-8")           # чужой бой — не трогаем
    m.parse_json_file(_write_dump(tmp_path, True), obs_dir=str(obs_dir))
    assert not stale.exists(), "старые sidecar-шаги того же battle_uid обязаны умирать"
    assert other.exists()
    assert (obs_dir / "abc123def0_step0.json").exists()


#--- вьюер: проводка ссылки/модалки наблюдения (не молча лишить нас клика) ----------
def test_viewer_wires_obs_link():
    here = os.path.dirname(os.path.abspath(__file__))
    html = open(os.path.join(here, "..", "tools", "trace_viewer", "viewer.html"),
                encoding="utf-8").read()
    assert "st.obsFile" in html                       # ссылка в инспекторе шага
    assert "showObsModal" in html                     # модалка читает sidecar через fetch
    assert "obsLink" in html                          # привязка клика после innerHTML
    assert "popObsBtn" in html                        # кнопка «состав хода» в попапе бойца
