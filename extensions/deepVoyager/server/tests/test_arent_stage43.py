# tests/test_arent_stage43.py — Этап 5: плейграунд «1-4 на 1-4» (арены для манёвров).
#
# Дизайн (просьба пользователя): стороны по 1..4 бойца. ГЕЙТЫ — симметричные NvN (N∈{1..4}) =>
# честный A/B (cand_alive==opp_alive, swap_sides играет равные стороны). ОБУЧЕНИЕ — все
# симметричные 1..4 + численные асимметрии (учится рвать дистанцию рывком, отступать из-под Ao,
# уклоняться в меньшинстве). Открытое поле (без стен). Схема НЕ растёт: MAX_TEAM=6 / K_ALLIES=6 /
# K_TARGETS=8 покрывают 4+4.
import itertools

from playground import arena
from arent import scenarios, team_eval
from planner.context import BattleContext

STAGE3_CLASSES = ("melee", "fast", "reach", "ranged", "mobile_archer", "tank")


def _counts(raw):
    a = [t for t in raw["tokens"] if t["disposition"] == -1]
    b = [t for t in raw["tokens"] if t["disposition"] == 1]
    return len(a), len(b)


#--- 1. КАНОН = симметричные NvN, N∈{1..4}, structured, без стен --------------------
def test_stage43_canon_symmetric_within_1_4():
    pool = scenarios.generate_stage43_canon(2, seed=2026)
    assert pool, "канон 43 пуст"
    for name, raw, p in pool:
        assert name.startswith("s43w_"), f"{name}: канон-имя вне s43w_*"
        assert 1 <= p["n_allies"] <= 4 and p["n_allies"] == p["n_foes"], \
            f"{name}: канон должен быть симметричным NvN, N∈1..4"
        assert _counts(raw) == (p["n_allies"], p["n_foes"]), f"{name}: токены не совпадают с размером"
        assert p["layout"] == "structured" and p["wall_profile"] == "open"
        assert p["n_walls"] == 0
    # весь диапазон размеров представлен
    assert {p["n_allies"] for _n, _r, p in pool} == {1, 2, 3, 4}
    # покрывает полные 36 упорядоченных пар базовых классов
    ordered = {(p["side_a_classes"][0], p["side_b_classes"][0]) for _n, _r, p in pool}
    assert ordered == set(itertools.product(STAGE3_CLASSES, STAGE3_CLASSES))


def test_stage43_canon_valid_fights():
    for name, raw, _p in scenarios.generate_stage43_canon(2, seed=9):
        payload = arena.build_payload(raw, name)
        ctx = BattleContext.from_payload(payload)
        assert ctx.hostile_targets() and ctx.src.is_alive and payload.get("weapons")


def test_stage43_canon_deterministic():
    a = scenarios.generate_stage43_canon(2, seed=777)
    b = scenarios.generate_stage43_canon(2, seed=777)
    assert [x[0] for x in a] == [x[0] for x in b]
    assert [str(x[2]["field"]) for x in a] == [str(x[2]["field"]) for x in b]


#--- 2. УЧЕБНЫЙ пул = симметричные 1..4 + асимметрии, random, без стен --------------
def test_stage43_pool_spans_sizes_and_asymmetry():
    pool = scenarios.generate_stage43_pool(1, seed=404)
    assert pool, "пул 43 пуст"
    counts = {_counts(raw) for _n, raw, _p in pool}
    for n in (1, 2, 3, 4):
        assert (n, n) in counts, f"нет симметричного {n}v{n} в пуле"
    assert any(a != b for a, b in counts), "нет численных асимметрий в пуле"
    # все стороны в диапазоне 1..4; открытое поле; случайная расстановка
    assert all(1 <= p["n_allies"] <= 4 and 1 <= p["n_foes"] <= 4 for _n, _r, p in pool)
    assert all(p["wall_profile"] == "open" and p["n_walls"] == 0 and p["layout"] == "random"
               for _n, _r, p in pool)
    # имена: симметрия -> s43_, асимметрия -> s43u_
    assert any(nm.startswith("s43u_") for nm, _r, _p in pool)
    assert any(nm.startswith("s43_") and not nm.startswith("s43u_") for nm, _r, _p in pool)


def test_stage43_pool_valid_fights():
    for name, raw, _p in scenarios.generate_stage43_pool(1, seed=5):
        payload = arena.build_payload(raw, name)
        ctx = BattleContext.from_payload(payload)
        assert ctx.hostile_targets() and ctx.src.is_alive and payload.get("weapons")


#--- 3. smoke движка: 4v4 и 2v2 прогоняются fight_teams (без манёвров, схема 4) -----
def test_stage43_fight_teams_runs():
    # берём канон-сценарии с размерами 2 и 4
    by_size = {}
    for name, raw, p in scenarios.generate_stage43_canon(1, seed=31337):
        by_size.setdefault(p["n_allies"], (name, raw))
    for n in (2, 4):
        name, raw = by_size[n]
        payload = arena.build_payload(raw, name)
        row = team_eval.fight_teams(payload, "random", "random",
                                    candidate_is_foes=False, rounds_cap=6, schema=4)
        assert row["outcome"] in ("win", "loss", "draw", "open")
        assert row["candidate_steps"] + row["opponent_steps"] > 0
        assert row["candidate_alive"] <= n and row["opponent_alive"] <= n
