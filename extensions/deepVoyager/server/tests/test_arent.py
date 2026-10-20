# tests/test_arent.py — данные для обучения: наблюдение, слоты, кодировка, выборка.
#
# Проверяем не «красивые числа», а инварианты, на которых держится сеть: длина
# состояния фиксирована, маски считаются по настоящим слотам, пустой слот отличается
# от нулевой клетки, и главное — разметка учителя декодируется обратно в тот же план.
import os
import random

import pytest

from arent import capture, encode, paths, slots as slots_mod, spec
from arent.dataset import append, generate, load, payload_files, sample_one, save, split, state_key
from arent.observe import observe_payload
from arent.states import rebuild, src_candidates, variants
from arent.teacher import Teacher, pinned
from conftest import make_npc, make_scene_payload, make_weapon
from playground.arena import load_arena
from planner.context import BattleContext


@pytest.fixture
def scene():
    """Кобольд-пращник (src, -2) + союзник-кобольд + стражник-враг + нейтральный."""
    hero = make_npc("A", 50, 150, disposition=-2, hp=5, name="Кобольд",
                    speed=30, damage="1d4+1")
    hero.update({"ac": 12, "toHit": 4, "cr": 0.25,
                 "weapons": [make_weapon("sling", "Праща", damage="1d4+1", bonus=4,
                                         sure_ft=30, doubt_ft=120, ranged=True)]})
    foe = make_npc("B", 300, 150, disposition=1, hp=11, name="Стражник",
                   speed=30, damage="1d8+2", reach_ft=5)
    foe.update({"ac": 16, "toHit": 3})
    ally = make_npc("C", 50, 250, disposition=-2, hp=5, name="Кобольд", speed=30, damage="1d4+1")
    ally.update({"ac": 12, "toHit": 4, "weapons": hero["weapons"]})
    other = make_npc("D", 50, 50, disposition=0, hp=1, name="Крестьянин")
    payload = make_scene_payload(npcs=[hero, foe, ally, other], walls=[],
                                 weapons=hero["weapons"])
    payload.update({"src": "A", "token": "B", "speed": 30})
    return payload


def test_dims_are_consistent_with_feature_lists():
    d = spec.dims()
    assert d["state"] == (len(spec.ME_FEATURES) + spec.K_TARGETS * len(spec.ENEMY_FEATURES)
                          + spec.K_ALLIES * len(spec.ALLY_FEATURES)
                          + (spec.K_WEAPONS + 1) * len(spec.WEAPON_FEATURES)
                          + spec.PATCH_SIZE * spec.PATCH_SIZE)
    assert d["cells"] == spec.K_CELLS + 1 and d["targets"] == spec.K_TARGETS + 1


def test_hit_chance_follows_d20_and_falls_back():
    assert spec.hit_chance(3, 12, 0.5) == pytest.approx(0.6)     # 12 на d20
    assert spec.hit_chance(3, 25, 0.5) == spec.HIT_CHANCE_MIN    # недостижимо
    assert spec.hit_chance(20, 5, 0.5) == spec.HIT_CHANCE_MAX    # крит 20 не считается
    assert spec.hit_chance(3, 0, 0.55) == 0.55                   # КД не прислали


def test_observation_uses_raw_ac_and_to_hit(scene):
    obs = observe_payload(scene)
    assert obs["me"]["ac"] == 12 and obs["me"]["toHit"] == 4
    assert obs["me"]["cr"] == 0.25 and obs["me"]["rangeCells"] == 24
    foe = obs["enemies"][0]
    assert foe["id"] == "B" and foe["ac"] == 16
    assert foe["chanceOnMe"] == pytest.approx(0.6)               # +3 по КД 12
    assert obs["allies"][0]["id"] == "C" and obs["allies"][0]["hostile"] is False
    assert [o["id"] for o in obs["others"]] == ["D"]


def test_grid_marks_allies_with_a_and_enemies_with_e(scene):
    field = "".join(observe_payload(scene)["grid"])
    assert "@" in field and "A" in field and "E" in field and "T" in field
    assert len(observe_payload(scene)["grid"]) == spec.PATCH_SIZE


def test_state_has_fixed_length(scene):
    obs = observe_payload(scene)
    assert len(encode.state(obs)) == spec.dims()["state"]


def test_sample_slots_and_masks_are_aligned(scene):
    ctx, obs = _ctx_obs(scene)
    slots = slots_mod.build(ctx, obs)
    sample = encode.observation(ctx, obs, slots)
    assert len(sample["cells"]) == spec.K_CELLS + 1
    assert len(sample["cells"][0]) == len(spec.CELL_FEATURES)
    assert sum(sample["mask"]["cells"]) == len(slots.cells)
    assert sum(sample["mask"]["targets"]) == len(slots.targets) + 1   # + «не стрелять»
    assert sum(sample["mask"]["weapons"]) == len(slots.weapons) + 1   # + «не атаковать»


def test_padded_slot_is_inactive_but_still_indexed(scene):
    ctx, obs = _ctx_obs(scene)
    slots = slots_mod.build(ctx, obs)
    vec = encode.target_vectors(obs, slots)[spec.K_TARGETS]
    assert vec[0] == 0.0 and vec[1] > 0.0


def _ctx_obs(payload):
    ctx = BattleContext.from_payload(payload)
    return ctx, observe_payload(payload)


def test_teacher_label_decodes_back_to_the_same_plan():
    with pinned(rounds=1, time_limit_sec=0.5):
        payload = load_arena("corridor_archer")
        teacher = Teacher(rounds=1, time_limit_sec=0.5)
        sample, reason = sample_one("corridor_archer", payload, teacher, {"src": payload["src"]})
        assert reason == "ok", reason
        ctx, obs = _ctx_obs(payload)
        slots = slots_mod.build(ctx, obs)
        decoded = [a.to_dict() for a in slots_mod.decode(slots, sample["y"])]
        assert decoded == sample["meta"]["actions"]


def test_ensure_cell_puts_a_far_cell_into_slots(monkeypatch):
    payload = load_arena("pillars_three")
    ctx, obs = _ctx_obs(payload)
    monkeypatch.setattr(spec, "K_CELLS", 2)
    slots = slots_mod.build(ctx, obs)
    far = (ctx.src_cell[0] + 1, ctx.src_cell[1] + 1)
    index = slots_mod.ensure_cell(slots, ctx.src_cell, far, ["downright"])
    assert len(slots.cells) == spec.K_CELLS            # тесную клетку вытесняет
    assert slots.cells[index]["cell"] == far
    label = {"cell": index, "target": 0, "weapon": spec.NONE_SLOT}
    assert slots_mod.final_cell(ctx, slots_mod.decode(slots, label)) == far


def test_rebuild_moves_tokens_and_hurts_them(scene):
    payload = rebuild(scene, "A", cells={"B": (0, 0)}, hp={"A": 1})
    ctx, _obs = _ctx_obs(payload)
    assert ctx.cell_of(ctx.token("B")) == (0, 0)
    assert ctx.token("A").hp_current == 1


def test_src_candidates_are_tokens_with_own_weapons(scene):
    assert src_candidates(scene) == ["A", "C"]      # только у героя и его копии есть weapons[]


def test_variants_keep_the_fight_but_move_the_point(scene):
    rng = random.Random(5)
    metas = [m for _s, m in variants(scene, rng, count=2, rounds_max=1, src_ids=["A"])]
    assert [m["src"] for m in metas] == ["A", "A"]
    assert metas[0]["rounds"] == 0                  # первое — исходное состояние
    assert metas[1]["rounds"] >= 1                  # дальше — разыгранное продолжение


def test_generate_returns_samples_of_declared_schema(tmp_path):
    paths.set_workspace(str(tmp_path))
    with pinned(rounds=1, time_limit_sec=0.5):
        samples, stats = generate(count=3, seed=3, per_src=1, rounds_max=0,
                                  want_arenas=["glass_cannon", "corridor_archer",
                                               "fork_two_melee"], use_live=False)
    assert samples and stats["schema"] == spec.SCHEMA
    assert all(len(s["state"]) == spec.dims()["state"] for s in samples)
    assert all(s["y"]["cell"] >= 0 for s in samples)


def test_samples_roundtrip_through_jsonl(tmp_path):
    paths.set_workspace(str(tmp_path))
    samples = [{"schema": spec.SCHEMA, "y": {"cell": 1}}, {"schema": spec.SCHEMA, "y": {"cell": 2}}]
    save(samples, "unit", stats={"n": 2})
    assert load("unit") == samples
    train, val = split(samples, frac=0.5, seed=1)
    assert len(train) + len(val) == len(samples)


# ------------------------------------------------------------------ накопление выборки
def _sample(cell, arena="a", state=0.5):
    return {"schema": spec.SCHEMA, "state": [state], "y": {"cell": cell},
            "meta": {"arena": arena}}


def test_state_key_identifies_state_and_label_only():
    """Один и тот же вектор с одной разметкой — один ключ, хоть meta и различается."""
    assert state_key(_sample(1, "a")) == state_key(_sample(1, "b"))
    assert state_key(_sample(1)) != state_key(_sample(2))
    assert state_key(_sample(1, state=0.5)) != state_key(_sample(1, state=0.6))


def test_append_keeps_old_examples_and_skips_repeats(tmp_path):
    """Датасет растёт поверх старого: дообучение не должно терять прежние сценарии."""
    paths.set_workspace(str(tmp_path))
    old = [_sample(1), _sample(2)]
    save(old, "u")
    path, added, total = append([_sample(2), _sample(3)], "u")
    assert added == 1 and total == 3
    assert len(load("u")) == 3 and load("u")[2]["y"]["cell"] == 3
    assert path.endswith("u.jsonl")


def test_append_into_a_missing_file_just_writes(tmp_path):
    paths.set_workspace(str(tmp_path))
    _path, added, total = append([_sample(1)], "fresh")
    assert (added, total) == (1, 1)


# ------------------------------------------------------------------ сбор живых состояний
def test_capture_writes_a_new_state_only_once(tmp_path, scene):
    """Каждый /plan обязан оставлять состояние, но дубли одного и того же не плодим."""
    paths.set_workspace(str(tmp_path))
    first = capture.capture(scene, {"actions": []}, event="e1")
    assert first and first.endswith(".json")
    assert os.path.exists(first)
    assert capture.capture(scene, {"actions": []}, event="e2") is None
    moved = rebuild(scene, "A", cells={"B": (0, 0)})
    assert capture.capture(moved, {"actions": []}, event="e3")


def test_captured_states_join_the_generation_sources(tmp_path, scene):
    """Снятое состояние сразу попадает в sources() — его берёт следующий gen."""
    paths.set_workspace(str(tmp_path))
    capture.capture(scene, {"actions": []})
    names = [name for name, _payload in payload_files()]
    assert names and names[0].startswith("cap_")


def test_capture_prunes_the_oldest_files(tmp_path, scene, monkeypatch):
    paths.set_workspace(str(tmp_path))
    monkeypatch.setattr(capture, "MAX_FILES", 2)
    for dy in range(4):
        capture.capture(rebuild(scene, "A", cells={"B": (dy, 0)}), {"actions": []})
    assert len(capture.files()) == 2


def test_capture_respects_the_switch_off(tmp_path, scene, monkeypatch):
    paths.set_workspace(str(tmp_path))
    monkeypatch.setenv("ARENT_CAPTURE", "0")
    assert capture.capture(scene, {"actions": []}) is None
    assert capture.files() == []
