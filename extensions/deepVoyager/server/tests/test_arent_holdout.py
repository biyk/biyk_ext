# tests/test_arent_holdout.py — командный holdout v2 (ho2_*) и его резерв (коммит №6).
#
# Проверяем инварианты честной оценки, а не сами сцены: is_independent отсекает и старый
# ho_, и новый ho2_ (обучение/abset их не видят); инициатива арены доезжает из raw-файла в
# Token (arena SIM_FIELDS -> payload -> parse_tokens); набор детерминирован по seed (два
# build = байт-в-байт), у КАЖДОГО токена явная инициатива 1..30, имена только ho2_*; write
# кладет файлы, не трогая боевой каталог; CLI expose'ит команду holdout и флаг rl --team-reward.
import json

import pytest

from arent import dataset, holdout
from arent.cli import parser
from conftest import make_npc, make_scene_payload
from planner.context import BattleContext


#--- 1. резерв независимого набора -------------------------------------------
@pytest.mark.parametrize("name,expected", [
    ("ho_open_duel", True), ("ho2_line_00", True), ("ho2_bridge_11", True),
    ("gen_line_003", False), ("corridor_archer", False), ("cap_live_01", False),
])
def test_is_independent_catches_ho_and_ho2(name, expected):
    assert dataset.is_independent(name) is expected


#--- 2. инициатива доезжает из арены до токена -------------------------------
def test_initiative_for_is_stable_and_in_range():
    a = holdout.initiative_for("ho2_x_00", "A")
    b = holdout.initiative_for("ho2_x_00", "A")
    assert a == b and 1 <= a <= 30
    assert len({holdout.initiative_for("ho2_x_00", f"T{i}") for i in range(40)}) > 1  # не константа


def test_arena_carries_initiative_into_token():
    hero = make_npc("A", 0, 0, disposition=-1, hp=10, initiative=17)
    foe = make_npc("B", 50, 0, disposition=1, hp=10, initiative=4)
    payload = make_scene_payload(npcs=[hero, foe], weapons=[{"id": "s", "name": "Меч",
                            "damage": "1d6", "attackBonus": 2, "sureFt": 5, "doubtFt": 5}])
    ctx = BattleContext.from_payload(payload)
    assert ctx.token("A").initiative == 17 and ctx.token("B").initiative == 4


#--- 3. сборка и заморозка набора --------------------------------------------
def test_build_renames_and_stamps_every_token():
    scenes = holdout.build(count=4, seed=holdout.HOLDOUT_SEED)
    assert scenes and len(scenes) <= 4
    for name, raw, params in scenes:
        assert name.startswith("ho2_") and dataset.is_independent(name)
        assert params["group_id"] == name
        assert raw["tokens"] and all(int(t.get("initiative", 0)) >= 1 for t in raw["tokens"])


def test_build_is_deterministic_by_seed():
    one = holdout.build(count=3, seed=12345)
    two = holdout.build(count=3, seed=12345)
    assert [n for n, _r, _p in one] == [n for n, _r, _p in two]
    assert [r["tokens"] for _n, r, _p in one] == [r["tokens"] for _n, r, _p in two]


def test_holdout_default_size_is_a_frozen_twelve():
    assert holdout.HOLDOUT_COUNT == 12


def test_write_lays_files_without_touching_real_arenas(tmp_path):
    scenes = holdout.build(count=3, seed=holdout.HOLDOUT_SEED)
    res = holdout.write(scenes, out_dir=str(tmp_path))
    assert res["written"] == len(scenes)
    for name, _raw, _params in scenes:
        path = tmp_path / f"{name}.json"
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert all(int(t.get("initiative", 0)) >= 1 for t in loaded["tokens"])


#--- 4. CLI expose -----------------------------------------------------------
def test_cli_exposes_holdout_command_with_defaults():
    args = parser().parse_args(["holdout"])
    assert args.cmd == "holdout" and args.count == holdout.HOLDOUT_COUNT
    assert args.seed == holdout.HOLDOUT_SEED


def test_cli_rl_defaults_to_team_reward_and_flags_can_disable():
    # WP4: без флагов дефолты RlConfig (team ±5, polyactor) не перебиваются;
    # legacy-путь A/B включается явными --no-team-reward / --mono-actor
    ns = parser().parse_args(["rl"])
    assert ns.team_reward is None and ns.polyactor is None
    off = parser().parse_args(["rl", "--no-team-reward", "--mono-actor",
                               "--draw-window", "6", "--reward-scale", "50"])
    assert off.team_reward is False and off.polyactor is False
    assert off.draw_window == 6 and off.reward_scale == 50
