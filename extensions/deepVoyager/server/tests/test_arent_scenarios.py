# tests/test_arent_scenarios.py — генератор независимых сценариев (structural diversity v2).
#
# Аудит показал: states.variants меняет лишь позиции/hp внутри ОДНОЙ арены (тот же состав
# врагов и то же оружие героя), поэтому разные seed — НЕ новые сценарии. scenarios.py строит
# сцены по структурным осям. Проверяем:
#   1) каждый сценарий — валидный бой (build_payload + BattleContext, есть кого бить, капитан жив);
#   2) детерминизм: один seed -> те же имена и params (учитель и политика видят один старт);
#   3) независимость: ни ho_*, ни ho2_*; group_id уникальны; это учебный материал;
#   4) структурное разнообразие: size команд, классы, арсенал, поля, стены, deployment;
#   5) random_start: рандом меняет расстановку между seed; structured — канон без джиттера;
#   6) границы/разделение: клетки в рамке, не наслаиваются, composed 1..6 на обеих сторонах;
#   7) write_arenas отказывается писать ho_* и ho2_*.
import math

from playground import arena
from arent import dataset, scenarios
from arent import scenario_layout as sl


def _pool(count=24, seed=5, random_start=None):
    return scenarios.generate(count, seed, random_start=random_start)


def _grid(raw):
    return raw["scene"]["height"] // sl.GRID, raw["scene"]["width"] // sl.GRID


#--- 1. каждый сценарий — валидный, обучаемый бой -----------------------------
def test_every_generated_scenario_is_a_valid_fight():
    scen = _pool()
    assert scen, "генератор не выдал ни одного сценария"
    for name, raw, params in scen:
        payload = arena.build_payload(raw, name)
        ctx = scenarios._bc(payload)
        assert ctx.hostile_targets(), f"{name}: нет живых врагов"
        assert ctx.src.is_alive, f"{name}: первый токен не жив на старте"
        assert payload.get("weapons"), f"{name}: у src нет оружия"
        assert params["n_foes"] == len(ctx.hostile_targets())


#--- 2. детерминизм по семени -------------------------------------------------
def test_generate_is_deterministic_for_a_seed():
    a = [(n, p["seq"], str(sorted(p.items()))) for n, _r, p in scenarios.generate(10, 3)]
    b = [(n, p["seq"], str(sorted(p.items()))) for n, _r, p in scenarios.generate(10, 3)]
    assert a == b


#--- 3. независимость от зарезервированных ho_*/ho2_* ------------------------
def test_generated_scenarios_never_touch_the_reserved_set():
    scen = _pool()
    produced = {n for n, _r, _p in scen}
    reserved = {n for n in arena.list_arenas() if dataset.is_independent(n)}
    assert not any(n.startswith("ho_") or n.startswith("ho2_") for n in produced)
    assert produced & reserved == set()
    groups = [p["group_id"] for _n, _r, p in scen]
    assert len(groups) == len(set(groups))
    for n in produced:
        assert dataset.is_independent(n) is False


#--- 4. структурное разнообразие (то, чего не даёт смена seed) ---------------
def test_pool_varies_structure_not_just_seed():
    scen = _pool(count=40, seed=11)
    foe_counts = {p["n_foes"] for _n, _r, p in scen}
    ally_counts = {p["n_allies"] for _n, _r, p in scen}
    classes = {c for _n, _r, p in scen for c in p["side_b_classes"]} | \
              {c for _n, _r, p in scen for c in p["side_a_classes"]}
    arsenals = {a for _n, _r, p in scen for a in p["side_a_arsenals"]}
    fields = {p["field_profile"] for _n, _r, p in scen}
    walls = {p["wall_profile"] for _n, _r, p in scen}
    deploy = {p["deployment"] for _n, _r, p in scen}
    assert len(foe_counts) >= 2, "число врагов не варьируется"
    assert len(ally_counts) >= 2, "число своих не варьируется (нет союзников)"
    assert classes >= {"melee", "ranged"} or len(classes) >= 3, "классы однообразны"
    assert len(arsenals) >= 2, "арсеналы однообразны"
    assert len(fields) >= 2, "размер поля не варьируется"
    assert len(walls) >= 2, "профиль стен не варьируется"
    assert len(deploy) >= 2, "deployment не варьируется"
    assert any(p["n_walls"] > 0 for _n, _r, p in scen), "нет ни одной сцены со стенами"


def test_wall_profile_independent_of_archetype():
    """Один и тот же архетип встречается с разными профилями стен (стены не из архетипа)."""
    by_arch = {}
    for _n, _r, p in _pool(count=60, seed=21):
        by_arch.setdefault(p["archetype"], set()).add(p["wall_profile"])
    assert any(len(prof) >= 2 for prof in by_arch.values()), \
        "профиль стен жёстко привязан к архетипу"


def test_wall_budget_within_bounds():
    for _n, _r, p in _pool(count=40, seed=8):
        assert 0 <= p["n_walls"] <= 20
        if p["wall_profile"] == "open":
            assert p["n_walls"] == 0


#--- 5. random_start: рандомная расстановка vs канон -------------------------
def test_random_start_moves_starting_positions_across_seeds():
    hero_cells = set()
    for seed in (1, 2, 3, 4, 5, 6):
        _name, raw, _p = scenarios.build(7, seed, random_start=True)
        hero_cells.add(tuple(raw["tokens"][0]["cell"]))
    assert len(hero_cells) >= 2, "рандомная расстановка не меняет старт от seed к seed"


def test_structured_layout_is_canonical_and_reproducible():
    _n1, raw1, p1 = scenarios.build(9, 4, random_start=False)
    _n2, raw2, p2 = scenarios.build(9, 4, random_start=False)
    assert p1["layout"] == "structured"
    assert [t["cell"] for t in raw1["tokens"]] == [t["cell"] for t in raw2["tokens"]]


def test_tactical_archetypes_default_to_structured():
    """Без override тактические архетипы идут канонически (стабильная задача для A/B)."""
    layouts = {p["archetype"]: p["layout"] for _n, _r, p in _pool(count=60, seed=33)}
    for arch in layouts:
        if arch in scenarios.TACTICAL:
            assert layouts[arch] == "structured", f"{arch} должен быть structured"
        else:
            assert layouts[arch] == "random", f"{arch} должен быть random"


#--- 6. границы поля и разделение команд -------------------------------------
def _cross_distance(ours, foes):
    return min(math.dist((a[0], a[1]), (b[0], b[1])) for a in ours for b in foes)


def test_tokens_in_bounds_and_not_stacked():
    for name, raw, p in _pool(count=40, seed=13):
        rows, cols = _grid(raw)
        assert 14 <= rows <= 32 and 14 <= cols <= 32, f"{name}: поле вне [14,32]"
        assert 1 <= p["n_allies"] <= 6 and 1 <= p["n_foes"] <= 6, f"{name}: состав вне [1,6]"
        cells = [tuple(t["cell"]) for t in raw["tokens"]]
        assert len(cells) == len(set(cells)), f"{name}: юниты в одной клетке"
        for r, c in cells:
            assert sl.MARGIN <= r <= rows - 1 - sl.MARGIN, f"{name}: ряд вне рамки"
            assert sl.MARGIN <= c <= cols - 1 - sl.MARGIN, f"{name}: столбец вне рамки"


def test_structured_teams_start_separated():
    """В каноне команды разнесены (бой не стартует в плотной свалке)."""
    for name, raw, _p in _pool(count=40, seed=17, random_start=False):
        ours = [tuple(t["cell"]) for t in raw["tokens"] if t["disposition"] == -1]
        foes = [tuple(t["cell"]) for t in raw["tokens"] if t["disposition"] == 1]
        assert _cross_distance(ours, foes) >= 3, f"{name}: команды слиплись на старте"


#--- 7. write_arenas не пишет зарезервированные имена ------------------------
def test_write_arenas_refuses_to_emit_reserved_names(tmp_path):
    good = ("gen_duel_001", {"tokens": []}, {"group_id": "gen_duel_001",
            "seed": 1, "archetype": "duel"})
    evil = ("ho_imposter", {"tokens": []}, {"group_id": "ho_imposter",
            "seed": 1, "archetype": "x"})
    evil2 = ("ho2_imposter", {"tokens": []}, {"group_id": "ho2_imposter",
             "seed": 1, "archetype": "x"})
    report = scenarios.write_arenas([good, evil, evil2], out_dir=str(tmp_path))
    assert report["written"] == 1
    assert (tmp_path / "gen_duel_001.json").exists()
    assert not (tmp_path / "ho_imposter.json").exists()
    assert not (tmp_path / "ho2_imposter.json").exists()
