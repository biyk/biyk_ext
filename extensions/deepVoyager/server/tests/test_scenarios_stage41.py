# tests/test_scenarios_stage41.py — Этап 4.1: командные бои с союзником.
#
# Дизайн (уточнение пользователя): ГЕЙТЫ — симметричные 2v2 (обе стороны по 2 бойца) =>
# вин-рейт честно считается (cand_alive==opp_alive на старте, swap_sides даёт ровно равные
# стороны). ОБУЧЕНИЕ — микс 2v2 + СЛУЧАЙНЫЕ 1v2 (численное неравенство, «учатся выживать»),
# в гейт 1v2 не входят. Союзник — второй боец стороны, класс рисуется случайно из 6 (оружие
# по профилю его класса); базовый боец пары остаётся классом matchup'а (все со всеми 6×6).
# Схема наблюдения 4 не меняется: MAX_TEAM=6 / K_ALLIES=6 покрывают 2 бойца на сторону.
import itertools

from playground import arena
from arent import scenarios, team_eval
from planner.context import BattleContext

STAGE3_CLASSES = ("melee", "fast", "reach", "ranged", "mobile_archer", "tank")


def _counts(raw):
    a = [t for t in raw["tokens"] if t["disposition"] == -1]
    b = [t for t in raw["tokens"] if t["disposition"] == 1]
    return len(a), len(b)


#--- 1. КАНОН гейта = 2v2 (симметрия, structured, без стен, детерминизм) ----------
def test_stage41_canon_is_symmetric_2v2():
    pool = scenarios.generate_stage41_canon(2, seed=2026)
    assert pool, "канон 4.1 пуст"
    for name, raw, p in pool:
        assert name.startswith("s41w_"), f"{name}: канон-имя вне s41w_*"
        assert p["n_allies"] == 2 and p["n_foes"] == 2, f"{name}: канон должен быть 2v2"
        assert _counts(raw) == (2, 2), f"{name}: токены не 2v2"
        assert p["layout"] == "structured" and p["wall_profile"] == "open"
        assert p["n_walls"] == 0 and p["field_profile"] == "medium"
    # покрывает полные 36 упорядоченных пар по БАЗОВЫМ классам сторон
    ordered = {(p["side_a_classes"][0], p["side_b_classes"][0]) for _n, _r, p in pool}
    assert ordered == set(itertools.product(STAGE3_CLASSES, STAGE3_CLASSES))
    # бои валидны
    for name, raw, _p in pool:
        payload = arena.build_payload(raw, name)
        ctx = BattleContext.from_payload(payload)
        assert ctx.hostile_targets() and ctx.src.is_alive and payload.get("weapons")


def test_stage41_canon_deterministic():
    a = scenarios.generate_stage41_canon(2, seed=777)
    b = scenarios.generate_stage41_canon(2, seed=777)
    assert [x[0] for x in a] == [x[0] for x in b]
    assert [str(x[2]["field"]) for x in a] == [str(x[2]["field"]) for x in b]


#--- 2. УЧЕБНЫЙ пул = микс 2v2 + случайные 1v2 (обе ориентации) -------------------
def test_stage41_pool_mixes_2v2_and_1v2():
    pool = scenarios.generate_stage41_pool(2, seed=404)
    counts = {_counts(raw) for _n, raw, _p in pool}
    assert (2, 2) in counts, "нет 2v2 в учебном пуле"
    assert (1, 2) in counts or (2, 1) in counts, "нет 1v2 в учебном пуле"
    # training pool — случайная расстановка, без стен
    assert all(p["layout"] == "random" and p["wall_profile"] == "open" and p["n_walls"] == 0
               for _n, _r, p in pool)
    # обе ориентации неравенства встречаются (учим и выживать, и прессинговать)
    assert (1, 2) in counts and (2, 1) in counts
    # имена: 2v2 -> s41_, 1v2 -> s41u_
    assert any(n.startswith("s41u_") for n, _r, _p in pool)
    assert any(n.startswith("s41_") and not n.startswith("s41u_") for n, _r, _p in pool)


def test_stage41_pool_valid_fights():
    for name, raw, _p in scenarios.generate_stage41_pool(2, seed=5):
        payload = arena.build_payload(raw, name)
        ctx = BattleContext.from_payload(payload)
        assert ctx.hostile_targets() and ctx.src.is_alive and payload.get("weapons")


#--- 3. союзник: случайный класс из 6, базовый = класс matchup'а -------------------
def test_stage41_ally_class_is_random_from_pool():
    seen = set()
    for sd in (1, 2, 3, 4, 5, 6, 7, 8):
        for _n, _r, p in scenarios.generate_stage41_canon(1, seed=sd):
            assert p["side_a_classes"][0] in STAGE3_CLASSES
            assert p["side_b_classes"][0] in STAGE3_CLASSES
            # союзники (2-е бойцы) — тоже валидные классы
            assert p["side_a_classes"][1] in STAGE3_CLASSES
            assert p["side_b_classes"][1] in STAGE3_CLASSES
            seen.add(p["side_a_classes"][1])
    assert len(seen) > 1, "класс союзника не варьируется (не случайный)"


#--- 4. обратная совместимость: build без новых параметров = как раньше ------------
def test_stage41_build_backward_compatible():
    _name, raw, p = scenarios.build(0, seed=123, archetype="duel",
                                    classes=["melee"], foe_classes=["ranged"], n_side=1)
    assert p["n_allies"] == 1 and p["n_foes"] == 1
    assert _counts(raw) == (1, 1)
    assert p["side_a_classes"] == ["melee"] and p["side_b_classes"] == ["ranged"]
    # зеркальный путь без новых параметров тоже живёт (n_allies==n_foes)
    _n2, raw2, p2 = scenarios.build(1, seed=99, archetype="duel", mirror=True,
                                    classes=["tank"], n_side=2)
    assert p2["n_allies"] == 2 and p2["n_foes"] == 2 and _counts(raw2) == (2, 2)


#--- 5. smoke движка: 2v2 прогоняется fight_teams (неравные стороны — отдельный тест) --
def test_stage41_fight_teams_runs_2v2():
    name, raw, _p = scenarios.generate_stage41_canon(1, seed=31337)[0]
    payload = arena.build_payload(raw, name)
    row = team_eval.fight_teams(payload, "random", "random",
                                candidate_is_foes=False, rounds_cap=6, schema=4)
    assert row["outcome"] in ("win", "loss", "draw", "open")
    assert row["candidate_steps"] + row["opponent_steps"] > 0
    assert row["candidate_alive"] <= 2 and row["opponent_alive"] <= 2
