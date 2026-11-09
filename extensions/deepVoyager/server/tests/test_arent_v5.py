# tests/test_arent_v5.py — Схема v5: maneuver head, 4D joint, encode, decode.
#
# Проверяем:
#  1. spec5: dims, константы, совместимость с v4.
#  2. net: _profile(5), groups_for, init_params, KNOWN_SCHEMAS.
#  3. joint: 4D legal_mask, argmax_v5, logz_v5, is_jointly_legal_v5, decode_v5.
#  4. encode_v5: observation, maneuver vectors, mask.
#  5. slots_v3.decode_v5: maneuver→use_action, weapon=NONE.
#  6. play.act: v5 dispatch path.
import math

import pytest

from arent import (backend, encode_v5, joint, net, play, slots_v3, spec, spec3, spec4, spec5)
from arent.observe import observe
from planner.context import BattleContext
from conftest import make_npc, make_scene_payload, make_weapon

NONE_T = joint.NONE_TARGET
NONE_W = joint.NONE_WEAPON
NONE_M = spec5.MANEUVER_NONE


# ─────────────────────────────────────────────────────────────────── helpers
def _melee_adjacent():
    a = make_npc("A", 0, 0, disposition=-1, hp=20, initiative=20)
    f = make_npc("F", 1 * 50, 0, disposition=1, hp=20, initiative=5)
    p = make_scene_payload(npcs=[a, f], weapons=[make_weapon("sw", damage="1d8+2", sure_ft=5)])
    p.update({"src": "A", "token": "F", "speed": 30})
    return p


def _v5_model(seed=7):
    return backend.build(net.Config(schema=5, hidden=16, head=4, seed=seed), kind="pure")


# ─────────────────────────────────────────────────────────────────── 1. spec5
class TestSpec5:
    def test_dims5_has_maneuvers(self):
        d = spec5.dims5()
        assert d["maneuvers"] == spec5.K_MANEUVERS + 1  # 4
        assert d["maneuver_feat"] == len(spec5.MANEUVER_FEATURES)  # 5
        assert d["schema"] == 5

    def test_dims5_superset_v4(self):
        d4 = spec4.dims4()
        d5 = spec5.dims5()
        # state/cells/targets/weapons identical
        for key in ("state", "cells", "targets", "weapons", "cell_feat", "weapon_feat", "grid"):
            assert d5[key] == d4[key], f"mismatch {key}"
        # v5 adds
        assert "maneuvers" in d5 and "maneuvers" not in d4

    def test_maneuver_kinds(self):
        assert spec5.K_MANEUVERS == 3
        assert spec5.MANEUVER_KINDS == ("dash", "disengage", "dodge")
        assert NONE_M == 3  # last slot


# ─────────────────────────────────────────────────────────────────── 2. net
class TestNetV5:
    def test_groups_for(self):
        assert net.groups_for(2) == net.GROUPS
        assert net.groups_for(4) == net.GROUPS
        assert net.groups_for(5) == net.GROUPS_V5
        assert "maneuvers" in net.groups_for(5)

    def test_profile_5(self):
        prof = net._profile(5)
        assert prof["dims"]["schema"] == 5
        assert "maneuvers" in prof["feats"]
        assert prof["y_key"]["maneuvers"] == "maneuver"

    def test_init_params_v5(self):
        cfg = net.Config(schema=5, hidden=8, head=4, seed=42)
        params = net.init_params(cfg)
        assert "maneuvers" in params["headW"]
        assert len(params["headW"]["maneuvers"]) == 4  # cfg.head rows
        assert len(params["headW"]["maneuvers"][0]) == 4 + len(spec5.MANEUVER_FEATURES)

    def test_param_count_v5(self):
        cfg = net.Config(schema=5, hidden=8, head=4, seed=42)
        count = net.param_count(cfg)
        # manually: trunk1(8×state + 8) + trunk2(4×8 + 4) + 4 heads * (4×(4+slot) + 4 + 4 + 1) + value
        # just check it's positive and larger than v4
        cfg4 = net.Config(schema=4, hidden=8, head=4, seed=42)
        assert count > net.param_count(cfg4)

    def test_known_schemas(self):
        assert 5 in net.KNOWN_SCHEMAS

    def test_feature_version_5(self):
        assert net.feature_version(5) == spec5.FEATURES_VERSION

    def test_check_compat_rejects_bad_dims(self):
        """Checkpoint with schema=5 but wrong maneuvers dim raises."""
        bad = {"schema": 5, "dims": {"maneuvers": 99, "cell_feat": 0,
                                     "weapon_feat": 0, "state": 0, "feat_version": 999}}
        with pytest.raises(ValueError, match="v5"):
            net._check_feature_compat(bad, "test")

    def test_check_compat_accepts_good(self):
        good = {"schema": 5, "dims": spec5.dims5()}
        net._check_feature_compat(good, "test")  # no exception


# ─────────────────────────────────────────────────────────────────── 3. joint 4D
class TestJointV5:
    def _full_mask(self):
        """4D mask at full production size for argmax/logz/legal tests."""
        totals = joint.group_totals_v5(5)
        p_n, t_n, w_n, m_n = totals["cells"], totals["targets"], totals["weapons"], totals["maneuvers"]
        mask = [[[[0] * m_n for _ in range(w_n)] for _ in range(t_n)] for _ in range(p_n)]
        # no-attack at pos 0 and pos 1 (maneuver=NONE)
        mask[0][NONE_T][NONE_W][NONE_M] = 1
        mask[1][NONE_T][NONE_W][NONE_M] = 1
        # dash at pos 0 (maneuver=0, force NONE_T/NONE_W)
        mask[0][NONE_T][NONE_W][0] = 1
        # attack from pos 1: target=0, weapon=0, maneuver=NONE
        mask[1][0][0][NONE_M] = 1
        return mask

    def test_argmax_v5_selects_attack(self):
        mask = self._full_mask()
        totals = joint.group_totals_v5(5)
        # craft logits: attack at (1, 0, 0, NONE_M) highest score
        cell_lp = [-10.0] * totals["cells"]
        target_lp = [-20.0] * totals["targets"]
        weapon_lp = [-20.0] * totals["weapons"]
        maneuver_lp = [-20.0] * totals["maneuvers"]
        cell_lp[1] = -1.0
        target_lp[0] = -0.5
        weapon_lp[0] = -0.5
        maneuver_lp[NONE_M] = -2.0
        result = joint.argmax_v5(mask, cell_lp, target_lp, weapon_lp, maneuver_lp, 5)
        assert result == {"plan": 1, "target": 0, "weapon": 0, "maneuver": NONE_M}

    def test_argmax_v5_selects_maneuver(self):
        mask = self._full_mask()
        totals = joint.group_totals_v5(5)
        cell_lp = [-10.0] * totals["cells"]
        target_lp = [-20.0] * totals["targets"]
        weapon_lp = [-20.0] * totals["weapons"]
        maneuver_lp = [-20.0] * totals["maneuvers"]
        # make (0, NONE_T, NONE_W, 0) [dash at pos 0] the best:
        cell_lp[0] = -1.0
        target_lp[NONE_T] = -1.0
        weapon_lp[NONE_W] = -1.0
        maneuver_lp[0] = -0.5  # dash > NONE_M
        maneuver_lp[NONE_M] = -3.0
        result = joint.argmax_v5(mask, cell_lp, target_lp, weapon_lp, maneuver_lp, 5)
        assert result == {"plan": 0, "target": NONE_T, "weapon": NONE_W, "maneuver": 0}

    def test_logz_v5_positive(self):
        mask = self._full_mask()
        totals = joint.group_totals_v5(5)
        cell_lp = [0.0] * totals["cells"]
        target_lp = [0.0] * totals["targets"]
        weapon_lp = [0.0] * totals["weapons"]
        maneuver_lp = [0.0] * totals["maneuvers"]
        z = joint.logz_v5(mask, cell_lp, target_lp, weapon_lp, maneuver_lp)
        assert z > float("-inf")

    def test_is_jointly_legal_v5(self):
        mask = self._full_mask()
        # no-attack at pos 0, NONE_M: legal
        assert joint.is_jointly_legal_v5({"plan": 0, "target": NONE_T, "weapon": NONE_W,
                                           "maneuver": NONE_M}, mask)
        # dash at pos 0: legal
        assert joint.is_jointly_legal_v5({"plan": 0, "target": NONE_T, "weapon": NONE_W,
                                           "maneuver": 0}, mask)
        # attack at pos 1 with NONE_M: legal
        assert joint.is_jointly_legal_v5({"plan": 1, "target": 0, "weapon": 0,
                                           "maneuver": NONE_M}, mask)
        # attack with dash: ILLEGAL (not in mask)
        assert not joint.is_jointly_legal_v5({"plan": 1, "target": 0, "weapon": 0,
                                              "maneuver": 0}, mask)


# ─────────────────────────────────────────────────────────────────── 4. encode_v5
class TestEncodeV5:
    def test_maneuver_vectors_shape(self):
        total = spec5.K_MANEUVERS + 1
        size = len(spec5.MANEUVER_FEATURES)
        slots = slots_v3.SlotsV3(
            plans=[], targets=[], weapons=[],
            maneuvers=[{"id": "dash_i", "kind": "dash"},
                        {"id": "diseng_i", "kind": "disengage"},
                        {"id": "dodge_i", "kind": "dodge"}])
        obs = {"me": {"actionRemaining": 1.0}}
        vecs = encode_v5.maneuver_vectors(obs, slots)
        assert len(vecs) == total
        assert all(len(v) == size for v in vecs)
        # dash slot (index 0) should have isDash=1
        assert vecs[0][1] == 1.0  # isDash
        # NONE slot (last) has slotActive=0
        assert vecs[-1][0] == 0.0

    def test_observation_has_maneuvers(self):
        ctx_payload = _melee_adjacent()
        ctx = BattleContext.from_payload(ctx_payload)
        obs = observe(ctx)
        slots = slots_v3.build(ctx, obs)
        slots.maneuvers = [{"id": "dash_i", "kind": "dash"}]
        sample = encode_v5.observation(ctx, obs, slots)
        assert sample["schema"] == spec5.SCHEMA
        assert "maneuvers" in sample
        assert "maneuvers" in sample["mask"]
        assert len(sample["maneuvers"]) == spec5.K_MANEUVERS + 1


# ─────────────────────────────────────────────────────────────────── 5. decode_v5
class TestDecodeV5:
    def test_maneuver_chosen_produces_use_action(self):
        """When maneuver != NONE, decode_v5 produces [move, USE(maneuver_item), move]."""
        plan = {"attack_cell": (0, 1), "end_cell": (0, 1), "dirs_in": ["right"],
                "dirs_out": [], "adx": 0, "ady": 1, "adist": 1, "edx": 0, "edy": 1,
                "edist": 1, "costIn": 1, "costOut": 0, "costTotal": 1,
                "retreatToOrigin": False, "pureMove": True}
        slots = slots_v3.SlotsV3(
            plans=[plan], targets=[], weapons=[],
            maneuvers=[{"id": "dash_item", "kind": "dash"},
                        {"id": "disengage_item", "kind": "disengage"},
                        {"id": "dodge_item", "kind": "dodge"}])
        label = {"plan": 0, "target": spec.NONE_SLOT, "weapon": spec.NONE_SLOT, "maneuver": 0}
        actions = slots_v3.decode_v5(slots, label)
        # should have move + USE(dash_item)
        from planner.action import ACTION_MOVE, ACTION_USE
        assert any(a.action == ACTION_USE and a.conf.get("itemId") == "dash_item"
                   for a in actions)
        # no target/attack use
        assert not any(a.conf.get("itemId") in ("sw",) for a in actions)

    def test_maneuver_none_produces_v4_decode(self):
        """When maneuver == NONE, decode_v5 falls through to normal v4 decode."""
        plan = {"attack_cell": (0, 0), "end_cell": (0, 0), "dirs_in": [],
                "dirs_out": [], "adx": 0, "ady": 0, "adist": 0, "edx": 0, "edy": 0,
                "edist": 0, "costIn": 0, "costOut": 0, "costTotal": 0,
                "retreatToOrigin": False, "pureMove": True}
        slots = slots_v3.SlotsV3(
            plans=[plan], targets=[{"id": "enemy_1", "name": "E", "alive": True}],
            weapons=[{"id": "sw", "name": "sword"}],
            maneuvers=[])
        label = {"plan": 0, "target": 0, "weapon": 0, "maneuver": NONE_M}
        actions = slots_v3.decode_v5(slots, label)
        from planner.action import ACTION_TARGET, ACTION_USE
        assert any(a.action == ACTION_TARGET for a in actions)
        assert any(a.action == ACTION_USE and a.conf.get("itemId") == "sw"
                   for a in actions)

    def test_label_of_v5_detects_maneuver(self):
        """label_of_v5 recognizes maneuver USE and forces weapon/target to NONE."""
        from planner.action import move_action, use_action
        ctx_payload = _melee_adjacent()
        ctx = BattleContext.from_payload(ctx_payload)
        obs = observe(ctx)
        slots = slots_v3.build(ctx, obs)
        slots.maneuvers = [{"id": "dash_item", "kind": "dash"},
                          {"id": "disengage_item", "kind": "disengage"},
                          {"id": "dodge_item", "kind": "dodge"}]
        # simulate Dash action: move + USE(dash_item)
        actions = [use_action("dash_item")]
        label = slots_v3.label_of_v5(ctx, slots, actions)
        assert label is not None
        assert label["maneuver"] == 0  # dash
        assert label["target"] == spec.NONE_SLOT
        assert label["weapon"] == spec.NONE_SLOT


# ─────────────────────────────────────────────────────────────────── 6. play.act v5
class TestPlayV5:
    def test_play_act_v5_runs(self):
        """End-to-end: v5 model produces actions through play.act dispatch."""
        payload = _melee_adjacent()
        # inject maneuvers into payload
        payload["maneuvers"] = [
            {"id": "dash_item", "kind": "dash", "name": "Рывок"},
            {"id": "disengage_item", "kind": "disengage", "name": "Отступление"},
            {"id": "dodge_item", "kind": "dodge", "name": "Уклонение"},
        ]
        model = _v5_model()
        result = play.act(model, payload)
        assert result["schema"] == 5
        assert "maneuver" in result["y"]
        assert "maneuver" in result["names"]
        assert "maneuvers" in result["counts"]
        assert result["decoder"] == "joint_argmax_v5"
        # action list is non-empty (some plan always exists)
        assert isinstance(result["actions"], list)

    def test_play_act_v5_no_attack_when_maneuver(self):
        """If model selects maneuver≠NONE, output actions should have USE(maneuver_item)."""
        # Build a stub that forces a maneuver selection
        payload = _melee_adjacent()
        payload["maneuvers"] = [
            {"id": "dash_item", "kind": "dash", "name": "Рывок"},
            {"id": "disengage_item", "kind": "disengage", "name": "Отступление"},
            {"id": "dodge_item", "kind": "dodge", "name": "Уклонение"},
        ]

        class _V5Stub:
            def __init__(self):
                self.cfg = net.Config(schema=5, hidden=16, head=4, seed=7)
                self.dims = net.dims_for(5)

            def head_logp(self, sample):
                totals = joint.group_totals(self.cfg.schema)
                pad = -1e30
                lcs = [pad] * totals["cells"]
                lts = [pad] * totals["targets"]
                lws = [pad] * totals["weapons"]
                # force no-attack (NONE target, NONE weapon) at plan 0
                lcs[0] = 1.0
                lts[NONE_T] = 1.0
                lws[NONE_W] = 1.0
                return lcs, lts, lws, 0.5

            def all_head_logp(self, sample):
                lcs, lts, lws, v = self.head_logp(sample)
                totals5 = joint.group_totals_v5(self.cfg.schema)
                lms = [-1e30] * totals5["maneuvers"]
                # force dash (index 0) as highest maneuver
                lms[0] = 2.0  # higher than NONE (lms[3])
                return lcs, lts, lws, lms, v

            def predict(self, sample):
                return {"plan": 0, "target": NONE_T, "weapon": NONE_W, "maneuver": 0,
                        "value": 0.5}

        model = _V5Stub()
        result = play.act(model, payload)
        # the label should have maneuver=0 (dash) and weapon=NONE
        assert result["y"]["maneuver"] == 0
        from planner.action import ACTION_USE
        use_actions = [a for a in result["actions"] if a.get("action") == "use"]
        assert any(a.get("conf", {}).get("itemId") == "dash_item" for a in use_actions)


# ─────────────────────────────────────────────────────────────────── 7. pure_net v5
class TestPureNetV5:
    def test_init_params_has_maneuvers(self):
        cfg = net.Config(schema=5, hidden=8, head=4, seed=42)
        model = backend.build(cfg, kind="pure")
        assert "maneuvers" in model.params["headW"]

    def test_forward_produces_maneuver_logits(self):
        cfg = net.Config(schema=5, hidden=8, head=4, seed=42)
        model = backend.build(cfg, kind="pure")
        d = spec5.dims5()
        # minimal valid sample
        total_m = d["maneuvers"]
        sample = {
            "state": [0.0] * d["state"],
            "cells": [[0.0] * d["cell_feat"]] * d["cells"],
            "targets": [[0.0] * d["target_feat"]] * d["targets"],
            "weapons": [[0.0] * d["weapon_feat"]] * d["weapons"],
            "maneuvers": [[0.0] * d["maneuver_feat"]] * total_m,
            "mask": {
                "cells": [1] * d["cells"],
                "targets": [1] * d["targets"],
                "weapons": [1] * d["weapons"],
                "maneuvers": [1] * total_m,
            },
        }
        *_, logits, _cache, value = model.forward(sample)
        assert "maneuvers" in logits
        allowed, values = logits["maneuvers"]
        assert len(values) == total_m  # all slots masked-in

    def test_all_head_logp_returns_5(self):
        cfg = net.Config(schema=5, hidden=8, head=4, seed=42)
        model = backend.build(cfg, kind="pure")
        d = spec5.dims5()
        sample = {
            "state": [0.0] * d["state"],
            "cells": [[0.0] * d["cell_feat"]] * d["cells"],
            "targets": [[0.0] * d["target_feat"]] * d["targets"],
            "weapons": [[0.0] * d["weapon_feat"]] * d["weapons"],
            "maneuvers": [[0.0] * len(spec5.MANEUVER_FEATURES)] * (spec5.K_MANEUVERS + 1),
            "mask": {
                "cells": [1] * d["cells"],
                "targets": [1] * d["targets"],
                "weapons": [1] * d["weapons"],
                "maneuvers": [1] * (spec5.K_MANEUVERS + 1),
            },
        }
        result = model.all_head_logp(sample)
        assert len(result) == 5  # cells, targets, weapons, maneuvers, value
