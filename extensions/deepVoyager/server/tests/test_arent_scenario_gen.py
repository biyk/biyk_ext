# tests/test_arent_scenario_gen.py — F-A: обучающие данные берутся из генератора боёв 1v1..6v6.
#
# До F-A тренировочный пул dataset.sources = 15 рукописных арен «герой против N» (own_actors=1),
# а симметричный генератор scenarios.generate был подключён только к abset/holdout. Здесь
# проверяем, что генерация обучающей разметки действительно строит КОМАНДные бои:
#   1) scenario_sources даёт валидные независимые сцены с командами (есть ≥2 своих бойцов);
#   2) sources()/generate() пропускают сценарный пул и помечают его group_id (meta.arena);
#   3) в выборке есть сценарий, размеченный с НЕСКОЛЬКИХ своих актёров (настоящий командный бой);
#   4) ho_/ho2_ не просачиваются; групповой split по независимым сценам непересекающийся;
#   5) фактическое число независимых сцен (групп) попадёт в статистику, а не только --count.
import json
import pathlib

from arent import cli, dataset, paths, splitting


def _small_pool(count=16, seed=101):
    pool, manifest = dataset.scenario_sources(count, seed)
    return pool, manifest


#--- 1. scenario_sources: валидные командные сцены ---------------------------
def test_scenario_sources_are_valid_and_have_team_battles():
    pool, manifest = _small_pool()
    assert pool, "scenario_sources не вернул ни одной сцены"
    assert len(pool) == len(manifest)
    own_counts = set()
    for name, payload in pool:
        assert not dataset.is_independent(name), f"holdout просочился в обучение: {name}"
        assert payload.get("weapons"), f"{name}: у лидера нет оружия"
        # посчитаем своих бойцов: src + токены той же диспозиции, не враждебные
        dispos = payload["data"]["npcs"]
        lead = payload["src"] or payload["token"]
        lead_disp = next(n["disposition"] for n in dispos if n["id"] == lead)
        own = sum(1 for n in dispos if n["disposition"] == lead_disp)
        own_counts.add(own)
    assert max(own_counts) >= 2, "генератор не выдаёт боёв с ≥2 своими бойцами"
    # манифест фиксирует composition/seed каждого сценария
    for params in manifest:
        assert {"group_id", "seed", "n_allies", "n_foes", "archetype"} <= set(params)


def test_scenario_sources_deterministic_for_seed():
    a = [n for n, _p in _small_pool(8, 7)[0]]
    b = [n for n, _p in _small_pool(8, 7)[0]]
    assert a == b and a, "одинаковый seed обязан давать одинаковый набор сцен"


#--- 2/3. sources/generate пропускают пул и размечают командные бои ----------
def test_sources_yields_scenario_pool_first():
    pool, _m = _small_pool(6, 3)
    names = [n for n, _p in dataset.sources(scenario_pool=pool, include_arenas=False,
                                             use_live=False)]
    assert names and names == [n for n, _p in pool]


def test_generate_labels_multi_actor_team_battles():
    pool, manifest = _small_pool(10, 55)
    samples, _stats = dataset.generate(count=60, per_src=2, teacher_rounds=1, rounds_max=1,
                                       want_arenas=[], use_live=False, include_arenas=False,
                                       scenario_pool=pool, scenario_manifest=manifest)
    assert samples, "разметка не собралась ни с одного сценария"
    # каждая выборка принадлежит независимой сцене (meta.arena = group_id)
    assert all(s["meta"].get("arena") for s in samples)
    # командный признак: хотя бы одна сцена дала разметку с >1 разных своих актёров
    srcs_by_arena = {}
    for s in samples:
        srcs_by_arena.setdefault(s["meta"]["arena"], set()).add(s["meta"]["src"])
    assert any(len(v) >= 2 for v in srcs_by_arena.values()), \
        "нет ни одного командного боя, размеченного с нескольких своих актёров"


#--- 4. holdout исключён, групповой split непересекающийся -------------------
def test_group_split_is_disjoint_over_scenarios():
    pool, manifest = _small_pool(12, 42)
    samples, _stats = dataset.generate(count=50, per_src=2, teacher_rounds=1, rounds_max=1,
                                       want_arenas=[], use_live=False, include_arenas=False,
                                       scenario_pool=pool, scenario_manifest=manifest)
    train, val, report = splitting.split_grouped(samples, frac=0.8, seed=7, strict=True)
    assert train and val
    assert report["group_overlap"] == []
    assert report["exact_state_overlap"] == []
    tr = {s["meta"]["arena"] for s in train}
    va = {s["meta"]["arena"] for s in val}
    assert tr & va == set()


#--- 5. статистика считает фактические независимые сцены ---------------------
def test_generate_reports_actual_group_count_not_requested_count():
    pool, manifest = _small_pool(10, 9)
    samples, stats = dataset.generate(count=1, per_src=2, teacher_rounds=1, rounds_max=1,
                                      want_arenas=[], use_live=False, include_arenas=False,
                                      scenario_pool=pool, scenario_manifest=manifest)
    # --count ограничивает число примеров, но группы (сцены) — отдельная метрика
    groups = {s["meta"]["arena"] for s in samples}
    assert len(groups) >= 1
    assert stats["groups"] == len(groups)
    assert stats["scenario_pool"] == len(pool)


#--- 6. CLI-обвязка: gen --scenarios реально пишет командный датасет ---------
def test_cli_gen_scenarios_writes_team_dataset(tmp_path):
    before = paths.workspace()
    paths.set_workspace(str(tmp_path))
    try:
        code = cli.main(["gen", "--scenarios", "5", "--scenarios-only", "--count", "10",
                         "--per-src", "2", "--teacher-rounds", "1", "--rounds-max", "1",
                         "--name", "fa_smoke"])
    finally:
        paths.set_workspace(before)
    assert code == 0
    jsonl = tmp_path / "data" / "samples" / "fa_smoke.jsonl"
    assert jsonl.exists()
    meta = pathlib.Path(str(jsonl) + ".meta.json")
    stats = json.loads(meta.read_text(encoding="utf-8"))
    assert stats["scenario_pool"] >= 1 and stats["groups"] >= 1
    assert stats.get("scenarios"), "манифест происхождения сцен не зафиксирован"
