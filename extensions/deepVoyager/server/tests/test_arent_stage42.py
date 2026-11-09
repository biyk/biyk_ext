# tests/test_arent_stage42.py — Этап 4.2: бои 3×3 на картах со стенами/укрытиями.
#
# teaching_plan §Этап 5 (укрытия + случайная расстановка) и §Этап 6 (3в3, rich geometry),
# объединённые в один учебный шаг. Ключевое отличие от 4.1: на карту добавлены непроходимые/
# затеняющие LOS стены, и стороны по 3 бойца. Инфраструктура стен/укрытий/узостей уже есть
# (scenario_layout/build_walls, planner/los, tactics_geom); здесь проверяем НОВЫЕ генераторы
# и НОВЫЙ инвариант связности:
#   1) generate_stage42_canon — симметричные 3в3, structured, НЕ пустые стены, все боеспособны;
#   2) generate_stage42_pool — 3в3 + асимметрия 2в3/3в2, random_start, стены ротируются;
#   3) СВЯЗНОСТЬ: ни одна сцена не печатает команду стеной (teams_reachable == True) — это держит
#      build_valid; отдельно проверяем сам примитив на синтетической запечатанной/дырявой карте;
#   4) детерминизм/стабильность канона: один (count_each, seed) -> идентичный набор (винрейты
#      сравнимы между прогонами); имена s42w_*/s42_*/s42u_* не коллидируют с s41_*/s3_*.
from playground import arena
from arent import scenarios, tactics_geom
from arent import scenario_layout as sl
from planner.context import BattleContext


#--- хелперы -------------------------------------------------------------------
def _assert_valid_and_reachable(scen, need_walls=True):
    assert scen, "генератор не выдал ни одной сцены"
    for name, raw, params in scen:
        payload = arena.build_payload(raw, name)
        ctx = scenarios._bc(payload)
        assert ctx.hostile_targets(), f"{name}: нет живых врагов"
        assert ctx.src.is_alive, f"{name}: src не жив на старте"
        assert payload.get("weapons"), f"{name}: у src нет оружия"
        # ГЛАВНЫЙ инвариант 4.2: стены не разрывают граф проходимости между командами.
        assert tactics_geom.teams_reachable(ctx), \
            f"{name}: команды в разных компонентах связности (бой невозможен)"
        if need_walls:
            assert params["n_walls"] >= 1, f"{name}: арена 4.2 обязана нести стены"


#--- синтетическая карта: запечатанная стена vs стена с проёмом ----------------
def _synthetic_ctx(walls, a_cell, b_cell):
    grid = sl.GRID
    rows = cols = 10

    def tok(tid, cell, disp):
        return {"id": tid, "name": tid, "disposition": disp,
                "x": cell[1] * grid, "y": cell[0] * grid, "width": grid, "height": grid,
                "center": {"x": (cell[1] + 0.5) * grid, "y": (cell[0] + 0.5) * grid},
                "hp": {"current": 10}}

    data = {"scene": {"width": cols * grid, "height": rows * grid, "gridSize": grid},
            "npcs": [tok("A", a_cell, -1), tok("B", b_cell, 1)], "walls": walls}
    return BattleContext.from_payload({"src": "A", "token": "B", "data": data, "speed": 30})


def _vwall(y0, y1, col=5):
    x = col * sl.GRID
    return {"id": f"w{y0}", "points": {"A": {"x": x, "y": y0}, "B": {"x": x, "y": y1}},
            "move": 1, "sight": 1}


def test_teams_reachable_flags_a_sealed_wall():
    """Сплошная вертикальная стена делит поле на два изолированных региона => бой невозможен."""
    sealed = [_vwall(0, 10 * sl.GRID)]                 # x=250 от y=0 до y=500 — глухая
    ctx = _synthetic_ctx(sealed, (5, 2), (5, 7))       # A слева, B справа
    assert not tactics_geom.teams_reachable(ctx)


def test_teams_reachable_accepts_a_gap_in_the_wall():
    """Тот же ряд, но в стене проём (строка 2 не закрыта) => команды соединены, бой возможен."""
    gapped = [_vwall(0, 2 * sl.GRID), _vwall(3 * sl.GRID, 10 * sl.GRID)]  # дыра y=100..150 (row2)
    ctx = _synthetic_ctx(gapped, (2, 2), (2, 7))       # оба в row2 — напротив проёма
    assert tactics_geom.teams_reachable(ctx)


def test_move_reachable_matches_component():
    """move_reachable из клетки A не включает отрезанную клетку B на глухой карте."""
    sealed = [_vwall(0, 10 * sl.GRID)]
    ctx = _synthetic_ctx(sealed, (5, 2), (5, 7))
    reach = tactics_geom.move_reachable(ctx, (5, 2))
    assert (5, 2) in reach
    assert (5, 7) not in reach


#--- 1. КАНОН 4.2 --------------------------------------------------------------
def test_stage42_canon_is_symmetric_3v3_with_walls_and_structured():
    scen = scenarios.generate_stage42_canon(2, 5)
    _assert_valid_and_reachable(scen)
    for name, raw, params in scen:
        assert name.startswith("s42w_"), f"{name}: канон 4.2 должен именоваться s42w_*"
        assert params["n_allies"] == 3 and params["n_foes"] == 3, f"{name}: не 3в3"
        assert params["wall_profile"] != "open", f"{name}: канон 4.2 обязан нести стены"
        assert params["layout"] == "structured", f"{name}: канон должен быть structured"
        assert params["field_profile"] == "medium", f"{name}: канон 4.2 — medium-поле"


def test_stage42_canon_is_deterministic_and_stable():
    a = [(n, str(sorted(p.items()))) for n, _r, p in scenarios.generate_stage42_canon(2, 42)]
    b = [(n, str(sorted(p.items()))) for n, _r, p in scenarios.generate_stage42_canon(2, 42)]
    assert a and a == b, "канон 4.2 должен быть идентичен при одном (count_each, seed)"


def test_stage42_canon_covers_wall_variety_across_pairs():
    scen = scenarios.generate_stage42_canon(1, 3)
    profiles = {p["wall_profile"] for _n, _r, p in scen}
    # Полный перебор 6×6 ротирует профили стен из _STAGE42_WALLS => представлены все.
    assert profiles == set(scenarios._STAGE42_WALLS), f"неполный набор стен: {profiles}"


#--- узкости (hold_choke/leave_choke): профиль bottleneck обязуется их давать -----
def test_bottleneck_is_a_stage42_wall_profile():
    """_STAGE42_WALLS несёт профиль, гарантирующий узость, иначе choke-теги не обучаемы."""
    assert "bottleneck" in scenarios._STAGE42_WALLS


def test_bottleneck_profile_produces_a_real_chokepoint():
    """Сплошная стена с ОДНОЙ клеточной дверью => клетка проёма = артикуляционная точка.

    build_valid проставляет params['has_choke'] по chokepoint_cells(ctx). Хоть один сгенерированный
    bottleneck-сценарий обязан дать has_choke=True (геометрия узости реально существует) и остаться
    связным (дверь соединяет половины -> teams_reachable). Без этого hold_choke/leave_choke мертвы."""
    produced = chokes = 0
    for seq in range(40):
        built = scenarios.build_valid(seq, 7, wall_profile="bottleneck", field_profile="medium",
                                      n_allies=3, n_foes=3, archetype="duel", random_start=False)
        if built is None:
            continue
        produced += 1
        _n, raw, p = built
        ctx = scenarios._bc(arena.build_payload(raw, _n))
        assert tactics_geom.teams_reachable(ctx), f"{_n}: bottleneck запечатал половины"
        if p["has_choke"]:
            chokes += 1
            ck = tactics_geom.chokepoint_cells(ctx)
            assert ck, "has_choke=True, но chokepoint_cells пуст"
    assert produced > 0, "bottleneck не производит связных сцен"
    assert chokes > 0, "bottleneck не порождает ни одной узости — choke-тактика необучаема"


#--- 2. УЧЕБНЫЙ ПУЛ 4.2 --------------------------------------------------------
def test_stage42_pool_has_3v3_and_asymmetry_and_random_layout():
    scen = scenarios.generate_stage42_pool(2, 9)
    _assert_valid_and_reachable(scen)
    sym = [p for n, _r, p in scen if n.startswith("s42_")]
    asym = [p for n, _r, p in scen if n.startswith("s42u_")]
    assert sym and asym, "нет ни симметричных 3в3, ни асимметричных 2в3/3в2"
    sizes = {(p["n_allies"], p["n_foes"]) for _n, _r, p in scen}
    assert (3, 3) in sizes, "нет симметричного 3в3"
    assert any(a != b for a, b in sizes), "нет численного неравенства (2в3/3в2)"
    assert any(p["layout"] == "random" for _n, _r, p in scen), "пул не использует random_start"
    walls = {p["wall_profile"] for _n, _r, p in scen}
    assert walls and "open" not in walls, f"в пуле 4.2 не должно быть открытых карт: {walls}"
    assert walls <= set(scenarios._STAGE42_WALLS), f"неизвестный профиль стен: {walls}"


def test_stage42_pool_names_do_not_collide_with_prior_stages():
    scen = scenarios.generate_stage42_pool(1, 2)
    names = {n for n, _r, _p in scen}
    groups = {p["group_id"] for _n, _r, p in scen}
    assert len(names) == len(set(names)) == len(groups), "имена/группы не уникальны"
    for n in names:
        assert n.startswith(("s42_", "s42u_")), f"{n}: имя вне неймспейса 4.2"


def test_stage42_pool_all_within_max_team():
    from arent.scenario_units import MAX_TEAM
    for _n, _r, p in scenarios.generate_stage42_pool(2, 21):
        assert p["n_allies"] + p["n_foes"] <= 2 * MAX_TEAM
        assert p["n_allies"] <= MAX_TEAM and p["n_foes"] <= MAX_TEAM


#--- 3. build_valid: связность — жёсткое условие -------------------------------
def test_build_valid_rejects_a_sealed_scenario():
    """build_valid не должен возвращать сцену, где teams_reachable == False.

    Проверяем сам механизм: перебираем много седел с плотным wall-профилем и убеждаемся, что
    каждый выпущенный сценарий связен (отбраковка запечатанных происходит внутри build_valid).
    """
    produced = 0
    for seq in range(60):
        built = scenarios.build_valid(seq, 991, wall_profile="pillars",
                                       field_profile="small", n_allies=3, n_foes=3,
                                       archetype="ring", random_start=False)
        if built is None:
            continue
        produced += 1
        _name, raw, _p = built
        ctx = scenarios._bc(arena.build_payload(raw, _name))
        assert tactics_geom.teams_reachable(ctx), f"{_name}: build_valid пропустил запечатанную карту"
    assert produced > 0, "build_valid не произвёл ни одной сцены — тест ничего не проверяет"
