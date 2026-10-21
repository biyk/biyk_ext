# tests/test_arent_spec_v2.py — контракт наблюдения v2 (командный бой, без раздувания патча).
#
# Коммит №1 плана: SCHEMA=2 + новые признаки (инициатива/акт-фракция/террейн) при НЕИЗМЕННОМ
# PATCH_R=5. Суть инвариантов: размерность состояния пинится конкретным числом (не «вырастет
# на 168»), encode отдаёт ровно ту же длину, что dims(), а новые признаки до появления
# инициативы в симуляции (коммит №2) заведомо нулевые. Заодно: чекпойнт старой схемы 1
# обязан быть отвергнут (net.load), перенос весов молча невозможен.
import json

import pytest

from arent import net, spec
from arent.encode import ally_slot, entity_slot, me_features, state
from arent.observe import observe_payload
from conftest import make_npc, make_scene_payload


@pytest.fixture
def scene():
    hero = make_npc("A", 50, 150, disposition=-1, hp=10, speed=30, damage="1d6")
    foe = make_npc("B", 300, 150, disposition=1, hp=10, speed=30, damage="1d8", reach_ft=5)
    ally = make_npc("C", 50, 250, disposition=-1, hp=10, speed=30, damage="1d6")
    weapons = [{"id": "sword", "name": "Меч", "damage": "1d6+2", "attackBonus": 3,
                "sureFt": 5, "doubtFt": 5}]
    payload = make_scene_payload(npcs=[hero, foe, ally], weapons=weapons)
    payload.update({"src": "A", "token": "B", "speed": 30})
    return payload


#--- 1. схема поднята, патч не раздут ----------------------------------------
def test_schema_is_v2_and_patch_radius_unchanged():
    assert spec.SCHEMA == 2
    assert spec.PATCH_R == 5 and spec.PATCH_SIZE == 11
    assert net.SCHEMA == spec.SCHEMA


def test_v2_features_present_and_degenerates_absent():
    for f in ("alliesActedFraction", "hasLosToNearestEnemy", "pathLenFrac", "wallsInView"):
        assert f in spec.ME_FEATURES
    assert "initiativeIndex" in spec.ENEMY_FEATURES and "isNextToAct" in spec.ENEMY_FEATURES
    assert "initiativeIndex" in spec.ALLY_FEATURES
    # вырожденные флаги (всегда константа от лица actora) в схему не попали
    assert "isCurrentActor" not in spec.ME_FEATURES
    assert "hasActedThisRound" not in spec.ME_FEATURES


#--- 2. размерность состояния зафиксирована числом ----------------------------
def test_state_dim_pinned_to_exact_number():
    d = spec.dims()
    assert d["state"] == 24 + 8 * 22 + 6 * 13 + 9 * 11 + 121
    assert d["state"] == 498
    assert d["target_feat"] == len(spec.ENEMY_FEATURES) == 22
    assert d["cells"] == spec.K_CELLS + 1


#--- 3. encode и dims не разъезжаются -----------------------------------------
def test_encode_state_matches_declared_dims(scene):
    obs = observe_payload(scene)
    assert len(state(obs)) == spec.dims()["state"]
    assert len(me_features(obs)) == len(spec.ME_FEATURES)
    foe = obs["enemies"][0]
    vec = entity_slot(foe, 0, spec.K_TARGETS + 1, obs["target"], obs["me"]["reachCells"])
    assert len(vec) == len(spec.ENEMY_FEATURES)
    ally = obs["allies"][0]
    assert len(ally_slot(ally, 0, spec.K_ALLIES)) == len(spec.ALLY_FEATURES)


def test_new_features_are_zero_until_sim_supplies_them(scene):
    """Коммит №1 фиксировал ФОРМУ. Коммит №3: террейн observe считает всегда, а
    признаки инициативы остаются нулём, пока порядок хода не передан (нет order)."""
    obs = observe_payload(scene)
    me = me_features(obs)
    # террейн считается без всякой инициативы (в этой сцене враг виден — LOS есть)
    assert me[spec.ME_FEATURES.index("hasLosToNearestEnemy")] == 1.0
    assert me[spec.ME_FEATURES.index("pathLenFrac")] > 0.0
    assert me[spec.ME_FEATURES.index("wallsInView")] == 0.0        # стен в сцене нет
    # инициативные признаки без порядка — ноль (заполняет observe с order из симуляции)
    assert me[spec.ME_FEATURES.index("alliesActedFraction")] == 0.0
    foe_vec = entity_slot(obs["enemies"][0], 0, spec.K_TARGETS + 1, obs["target"], 1.0)
    assert foe_vec[spec.ENEMY_FEATURES.index("initiativeIndex")] == 0.0
    assert foe_vec[spec.ENEMY_FEATURES.index("isNextToAct")] == 0.0


def test_terrain_features_recomputed_from_the_scene(scene):
    """Террейн-признаки берутся из реальной геометрии, а не захардкожены нулём."""
    from planner.context import BattleContext
    from arent.observe import observe
    ctx = BattleContext.from_payload(scene)
    obs = observe(ctx)
    # путь до ближайшего видимого врага nonzero и укладывается в патч (<=1)
    assert 0.0 < obs["me"]["pathLenFrac"] <= 1.0


#--- 4. чекпойнт старой схемы отвергается -------------------------------------
def test_net_load_refuses_a_schema_1_checkpoint(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"format": net.FORMAT, "schema": 1,
                                "config": {}, "params": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="SCHEMA"):
        net.load(str(path))
