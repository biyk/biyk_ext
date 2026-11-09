# tests/test_arent_dataset_v5.py — Этап 7-подготовка: v5-путь сэмплирования (maneuver-голова).
#
# Проверяем, что конвейер генерации выборки SCHEMA=5 ЖИВой и обучаемый (не заглушка):
#   1) SAMPLERS[5] зарегистрирован (generate(--schema 5) / train проходят по той же таблице);
#   2) sample_one_v5 на полигоне stage43 (юнитам розданы манёвры) даёт пример схемы 5:
#      feat_version/ширины (4 слота x 5 признаков) == spec5.dims5, y из 4 ключей, assert_compatible
#      его пропускает;
#   3) ПОЗИТИВНАЯ метка манёвра: кормим core готовым Labeled с use(Уклонение) -> y.maneuer==индекс
#      dodge, атака (target/weapon) форсится NONE, roundtrip decode_v5 собирает use обратно. Это
#      доказывает, что maneuver-голова получает ненулевой обучающий сигнал, а не только NONE.
# Никакого запуска тренировки (Q2 «готовить, не запускать») — только сквозной разбор состояний.
from playground import arena
from planner.action import use_action
from planner.context import BattleContext
from planner.sim import Simulation
from arent import dataset, scenarios, spec, spec5
from arent.battlecast import BattlecastTeacher
from arent.scenario_units import MANEUVER_ITEMS
from arent.teacher import Labeled


def _stage43_pool(n: int = 3, seed: int = 2026):
    """[(name, payload)] из canon-полигона 1-N vs 1-N: каждому бойцу розданы 3 манёвра."""
    out = []
    for name, raw, _params in scenarios.generate_stage43_canon(n, seed=seed):
        out.append((name, arena.build_payload(raw, name)))
    return out


#--- 1. реестр сэмплеров ─────────────────────────────────────────────────────────────
def test_samplers_registered_v5():
    assert dataset.SAMPLERS[spec5.SCHEMA] is dataset.sample_one_v5


#--- 2. end-to-end: stage43 -> пример схемы 5 с maneuver-группой фикс. ширины ────────
def test_sample_one_v5_produces_schema5_sample():
    pool = _stage43_pool()
    assert pool, "нет stage43-сцен"
    teacher = BattlecastTeacher()
    d5 = spec5.dims5()
    got = 0
    for name, payload in pool:
        ctx = BattleContext.from_payload(payload)
        assert tuple(m["kind"] for m in ctx.maneuver_items) == spec5.MANEUVER_KINDS, \
            "stage43 обязан раздавать манёвры актёру (иначе v5-голова мертва)"
        order = Simulation.of(ctx, env_seed=7).initiative_order
        sample, reason = dataset.sample_one_v5(name, payload, teacher, {"arena": name}, order)
        if reason != "ok":                       # часть состояний учитель не собирает в слоты
            continue
        got += 1
        assert sample["schema"] == spec5.SCHEMA
        assert sample["feat_version"] == spec5.FEATURES_VERSION
        assert set(sample["y"]) == {"plan", "target", "weapon", "maneuver"}
        assert len(sample["maneuvers"]) == d5["maneuvers"] == spec5.K_MANEUVERS + 1
        assert len(sample["maneuvers"][0]) == d5["maneuver_feat"]
        dataset.assert_compatible(sample)         # совместный пример — не бросает SchemaMismatch
    assert got, "ни один stage43-ход не размечен в схему 5"


#--- 3. позитивный манёвр: ненулевой обучающий сигнал maneuver-головы ────────────────
def test_positive_maneuver_label_roundtrips_to_use():
    name, payload = _stage43_pool()[0]
    ctx = BattleContext.from_payload(payload)
    dodge = next(m for m in MANEUVER_ITEMS if m["kind"] == "dodge")
    actions = [use_action(dodge["id"])]           # ход учителя-манёвра: только use (без удара)
    labeled = Labeled(ctx=ctx, actions=actions, value=0.0, score=0.0, depth=1)
    order = Simulation.of(ctx, env_seed=7).initiative_order

    sample, reason = dataset.sample_from_labeled_v5(name, labeled, {}, order)
    assert reason == "ok", reason
    m_idx = sample["y"]["maneuver"]
    assert m_idx == spec5.MANEUVER_KINDS.index("dodge") == 2
    # манёвр взаимоисключает атаку: цель/оружие форсируются в NONE-слот
    assert sample["y"]["target"] == spec.NONE_SLOT
    assert sample["y"]["weapon"] == spec.NONE_SLOT
    # one-hot идентичность манёвра в слоте 2 активна (голова видит «dodge», а не padding)
    vec = sample["maneuvers"][m_idx]
    assert vec[spec5.MANEUVER_FEATURES.index("isDodge")] == 1.0
    assert vec[spec5.MANEUVER_FEATURES.index("slotActive")] == 1.0
    dataset.assert_compatible(sample)


#--- 4. обратная совместимость: без предметов maneuver==NONE (путь v4) ──────────────
def test_no_maneuver_items_yields_none_head():
    name, payload = _stage43_pool(1)[0]
    payload = dict(payload)
    payload["maneuvers"] = []                      # снимаем предметы у актёра (legacy-сцена)
    teacher = BattlecastTeacher()
    ctx = BattleContext.from_payload(payload)
    order = Simulation.of(ctx, env_seed=7).initiative_order
    sample, reason = dataset.sample_one_v5(name, payload, teacher, {}, order)
    if reason != "ok":
        return                                     # состояние без разметки — не показательно
    assert sample["y"]["maneuver"] == spec5.MANEUVER_NONE
    # все реальные слоты padding (slotActive=0), NONE-слот активен -> маска не даёт учиться на пустоте
    real = sample["maneuvers"][:spec5.K_MANEUVERS]
    assert all(vec[spec5.MANEUVER_FEATURES.index("slotActive")] == 0.0 for vec in real)
