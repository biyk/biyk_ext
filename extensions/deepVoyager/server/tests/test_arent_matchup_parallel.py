# tests/test_arent_matchup_parallel.py — параллельный прогон боёв == последовательный.
#
# team_eval.matchup_parallel раскидывает НЕЗАВИСИМЫЕ бои по процессам (ProcessPoolExecutor).
# Доказываем, что распараллеливание не меняет результат, а только wall-time:
#  • пустой вход -> пустой вывод; один воркер -> тот же код без оверхеда пула;
#  • workers=1 (в том же процессе) совпадает с sequential matchup_sources по всем полям
#    строки, кроме имен политик (их задаёт run_name, не боёвка);
#  • реальный пул (workers>=2, отдельные spawn-процессы) совпадает с in-process по
#    ДЕТАЙ боевки (кто где ходил, исход, длительность). Сравнение на self-play чистых
#    весов и по tuning-независимым полям: conftest пинит коэффициенты лишь в родителе,
#    дети читают points.json — поэтому поля награды/урона (зависят от тюнинга) не сравниваем,
#    а выбор чистой политики = argmax по наблюдению (от тюнинга не зависит) — сравниваем весь.
import pytest

from arent import backend, net, team_eval
from conftest import make_npc, make_scene_payload, make_weapon


def _policy(seed=5):
    """Крошечная pure-политика (schema 2): argmax-головы, детерминирована, torch не нужен."""
    return backend.build(net.Config(hidden=8, head=6, seed=seed), kind="pure")


def _duel(dx, dy):
    a = make_npc("A", 0, 0, disposition=-1, hp=20, initiative=20)
    f = make_npc("F", dx * 50, dy * 50, disposition=1, hp=20, initiative=5)
    p = make_scene_payload(npcs=[a, f], weapons=[make_weapon("sw", damage="1d8+2", sure_ft=5)])
    p.update({"src": "A", "token": "F", "speed": 30})
    return p


def _sources():
    return [("d0", _duel(1, 0)), ("d1", _duel(3, 2)), ("d2", _duel(0, 5)), ("d3", _duel(6, 6))]


def _project(row):
    """Поля строки, независимые от тюнинга: имена сторон исключаем (их задаёт run_name)."""
    keep = ("name", "replay", "outcome", "raw_outcome", "rounds", "steps", "terminated",
            "truncated", "end_reason", "candidate_is_foes", "candidate_opened",
            "candidate_steps", "opponent_steps", "schema", "illegal_steps")
    out = {k: row[k] for k in keep if k in row}
    out["trace"] = [{"step": s["step"], "side": s["side"], "actor": s["actor"],
                     "executed": s["executed"], "illegal": s["illegal"]}
                    for s in row.get("trace", [])]
    return out


def test_matchup_parallel_empty_sources():
    assert team_eval.matchup_parallel("x", "greedy", []) == []


def test_matchup_parallel_single_worker_matches_sequential(tmp_path):
    """workers=1 (тот же процесс) == sequential matchup_sources по детальным полям боя."""
    path = net.save(_policy(), str(tmp_path / "m.json"))
    model = backend.load_policy(path, kind="auto")
    sources = _sources()
    seq = team_eval.matchup_sources(model, "greedy", sources, rounds_cap=5, draw_window=4,
                                    swap_sides=True, openings=True, rich_trace=True,
                                    shape_stage="stage3", trace_limit=0)
    par = team_eval.matchup_parallel(path, "greedy", sources, rounds_cap=5, draw_window=4,
                                     swap_sides=True, openings=True, rich_trace=True,
                                     shape_stage="stage3", trace_limit=0, workers=1)
    assert len(par) == len(seq)
    assert [_project(r) for r in par] == [_project(r) for r in seq]


@pytest.mark.skipif(not hasattr(team_eval, "matchup_parallel"), reason="parallel API absent")
def test_matchup_parallel_process_pool_matches_in_process(tmp_path):
    """Реальный пул процессов (self-play чистых весов) совпадает с in-process прогоном.

    self-play (candidate=opponent=путь): обе стороны водит argmax по наблюдению, который от
    тюнинга не зависит, поэтому сравнение корректно даже когда дети читают свой points.json."""
    path = net.save(_policy(seed=7), str(tmp_path / "sp.json"))
    sources = _sources()
    in_proc = team_eval.matchup_parallel(path, path, sources, rounds_cap=5, draw_window=4,
                                         swap_sides=True, openings=True, rich_trace=True,
                                         shape_stage="stage3", trace_limit=0, workers=1)
    pool = team_eval.matchup_parallel(path, path, sources, rounds_cap=5, draw_window=4,
                                      swap_sides=True, openings=True, rich_trace=True,
                                      shape_stage="stage3", trace_limit=0, workers=2)
    assert len(pool) == len(in_proc) > 0
    assert [_project(r) for r in pool] == [_project(r) for r in in_proc]
