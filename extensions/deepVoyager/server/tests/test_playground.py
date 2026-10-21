# tests/test_playground.py — площадка для тестирования стратегий (пункт 5).
#
# Арены — это обычные /plan-запросы с параметрами врагов; прогон — матрица
# «арена × глубина × таймер», где значение считается НЕ глазами планировщика,
# а независимой симуляцией на фиксированное число раундов.
import json

import pytest

from arent import dataset, paths
from arent.dataset import generate
from planner.context import BattleContext
from playground.arena import ARENA_NAMES, load_arena
from playground.run import format_table, main, run_matrix


def test_registered_arenas():
    assert set(ARENA_NAMES) >= {"fork_two_melee", "corridor_archer", "pillars_three",
                                "bruiser_death", "glass_cannon"}


def test_arena_library_is_broad_enough_to_train():
    """5 арён мало: без живых captures gen упирается в потолок ~десятков состояний.

    Библиотека раздута до 15 тактических архетипов; тест сторожит от регрессии,
    что кто-то удалит арены и снова обескровит offline-выборку.
    """
    assert len(ARENA_NAMES) >= 15


@pytest.mark.parametrize("name", ARENA_NAMES)
def test_arena_is_learnable_by_gen(name, tmp_path, monkeypatch):
    """Каждая арена обязана выдать хотя бы один размеченный пример, а не только валидный payload.

    Зарезервированные ho_* (независимый набор) генерация обычно вычищает по префиксу —
    но сама арена всё равно должна быть обучаемой, поэтому на время проверки глушим фильтр
    резерва (dataset.is_independent -> False): тестируем арену, а не политики отбора.
    """
    monkeypatch.setattr(dataset, "is_independent", lambda _n: False)
    paths.set_workspace(str(tmp_path))
    samples, stats = generate(count=4, seed=11, per_src=3, rounds_max=1,
                              teacher_rounds=1, teacher_limit=0.3,
                              want_arenas=[name], use_live=False)
    assert samples, f"{name}: gen не дал ни одного примера, пропуски {stats['skip']}"


@pytest.mark.parametrize("name", ARENA_NAMES)
def test_every_arena_is_a_valid_plan_payload(name):
    ctx = BattleContext.from_payload(load_arena(name))
    assert ctx.src.disposition != 0
    assert ctx.hostile_targets()                 # арена без врагов бессмысленна
    assert ctx.weapons                           # и без оружия тем более


@pytest.mark.parametrize("name", ARENA_NAMES)
def test_arena_keeps_its_own_hero_id(name):
    payload = load_arena(name)
    ctx = BattleContext.from_payload(payload)
    assert ctx.src_id == payload["src"]


def test_fork_arena_has_two_melee_foes_around_the_hero():
    ctx = BattleContext.from_payload(load_arena("fork_two_melee"))
    foes = ctx.hostile_targets()
    assert len(foes) == 2
    assert all(f.reach_ft == 5 for f in foes)    # ближники: угроза = соседняя клетка


def test_run_matrix_makes_one_row_per_combination():
    rows = run_matrix(names=["glass_cannon"], depths=(1, 2), timers=(0.5,))
    assert len(rows) == 2
    assert [(r.arena, r.rounds, r.timer) for r in rows] == [("glass_cannon", 1, 0.5),
                                                            ("glass_cannon", 2, 0.5)]
    for row in rows:
        assert row.latency >= 0.0
        assert row.depth >= 1 and row.nodes >= 0
        assert row.plan                          # чем-то он всё-таки ходит


def test_rows_carry_the_common_metric_and_plan_text():
    flat, deep = run_matrix(names=["bruiser_death"], depths=(1, 2), timers=(0.5,))
    assert isinstance(flat.value, float) and isinstance(deep.value, float)
    assert "move" in flat.plan and "target" in flat.plan
    assert deep.metric_rounds == flat.metric_rounds   # сравнение — в одной шкале


def test_deeper_search_does_not_loose_on_the_common_metric():
    rows = run_matrix(names=["fork_two_melee"], depths=(1, 2, 3), timers=(0.5,))
    assert len(rows) == 3
    assert rows[-1].value >= rows[0].value


def test_run_matrix_restores_tuning():
    from planner import points
    before = points.tuning()
    run_matrix(names=["pillars_three"], depths=(2,), timers=(0.5,))
    assert points.tuning() == before             # пин теста не должен «протечь»


def test_rows_are_json_serialisable():
    rows = run_matrix(names=["corridor_archer"], depths=(1,), timers=(0.5,))
    text = json.dumps([r.to_dict() for r in rows], ensure_ascii=False)
    assert "corridor_archer" in text


def test_format_table_shows_header_and_arena(tmp_path):
    rows = run_matrix(names=["glass_cannon"], depths=(1, 2), timers=(0.5,))
    text = format_table(rows)
    assert "арена" in text and "glass_cannon" in text
    assert text.count("glass_cannon") >= 2


def test_main_returns_zero_and_prints_table(capsys):
    assert main(["--arena", "fork_two_melee", "--rounds", "1,2", "--timers", "0.5"]) == 0
    out = capsys.readouterr().out
    assert "арена" in out and "fork_two_melee" in out


def test_main_can_write_a_report_file(tmp_path):
    target = tmp_path / "report.json"
    assert main(["--arena", "glass_cannon", "--rounds", "1", "--timers", "0.5",
                 "--json", str(target)]) == 0
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data[0]["arena"] == "glass_cannon"


def test_main_rejects_unknown_arena():
    assert main(["--arena", "nope", "--rounds", "1", "--timers", "0.5"]) == 2
