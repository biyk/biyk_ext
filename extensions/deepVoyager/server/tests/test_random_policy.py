# tests/test_random_policy.py — случайный соперник-baseline (§10.3, §7): legal + детерминизм.
#
# RandomController обязан: (1) выбирать ТОЛЬКО совместно допустимые тройки из obs['legal']
# (serve==train по множеству действий, legalize — тождество); (2) быть детерминированным по
# seed; (3) прогоняться в matchup как соперник. Это нижняя граница честной оценки (§0.1).
from arent import joint as joint_mod, polyenv, team_eval
from arent.tactics_config import TacticsConfig
from conftest import make_npc, make_scene_payload, make_weapon


def _npc(nid, col, disp, hp, ini, speed=30):
    return make_npc(nid, col * 50, 0, disposition=disp, hp=hp, speed=speed, initiative=ini)


def _scene():
    a1 = _npc("A1", 0, -1, 30, 20)
    f1 = _npc("F1", 1, 1, 12, 15)
    payload = make_scene_payload(npcs=[a1, f1], weapons=[make_weapon("sword", damage="1d6+2")])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


def _env_obs(payload, start_index=0):
    environment = polyenv.PolyFightEnv(rounds_cap=8, team=None)
    obs = environment.reset(payload, start_index=start_index)
    return environment, obs


def test_label_is_always_jointly_legal():
    environment, obs = _env_obs(_scene())
    ctrl = team_eval.RandomController(seed=1, schema=obs.get("schema", 2))
    for _ in range(12):
        label = ctrl.label(obs, environment._ctx, environment.slots)
        assert joint_mod.is_jointly_legal(label, obs["legal"], ctrl.schema)   # только из A(s)
        obs, _r, term, trunc, _i = environment.step(label)
        if term or trunc:
            break


def test_same_seed_same_label_sequence():
    environment, obs = _env_obs(_scene())
    a = team_eval.RandomController(seed=7, schema=2)
    b = team_eval.RandomController(seed=7, schema=2)
    seq_a = [a.label(obs, environment._ctx, environment.slots) for _ in range(6)]
    seq_b = [b.label(obs, environment._ctx, environment.slots) for _ in range(6)]
    assert seq_a == seq_b                                       # детерминирован по seed


def test_different_seed_can_diverge():
    environment, obs = _env_obs(_scene())
    a = team_eval.RandomController(seed=1, schema=2)
    b = team_eval.RandomController(seed=99, schema=2)
    seq_a = [a.label(obs, environment._ctx, environment.slots) for _ in range(6)]
    seq_b = [b.label(obs, environment._ctx, environment.slots) for _ in range(6)]
    assert seq_a != seq_b                                       # seed реально меняет выбор


def test_build_controller_recognizes_random():
    for name in ("random", "random_policy", "RandomPolicy"):
        ctrl = team_eval.build_controller(name, schema=2)
        assert isinstance(ctrl, team_eval.RandomController)
        assert ctrl._is_controller is True


def test_cli_accepts_random_opponent_and_flags():
    """Gate 0: --opponent random + новые флаги парсятся CLI (не только Python-API)."""
    from arent.cli import parser
    ns = parser().parse_args(["team-matchup", "--opponent", "random",
                              "--opponent-seed", "42", "--tactics"])
    assert ns.opponent == "random" and ns.opponent_seed == 42 and ns.use_tactics is True
    # без флагов — детерминированный дефолт (seed 0, tactics выкл)
    d = parser().parse_args(["team-matchup"])
    assert d.opponent_seed == 0 and d.use_tactics is False


def test_matchup_runs_against_random(tmp_path, monkeypatch):
    from arent import dataset, tactics_config
    monkeypatch.setattr(dataset, "independent_sources",
                        lambda *a, **k: [("ho_rand_win", _scene())])
    monkeypatch.setattr(team_eval.paths, "run_dir", lambda name: str(tmp_path))
    tactics_config.set_config(TacticsConfig(enabled_global=False))    # eval: shaping выкл
    try:
        report = team_eval.run_matchup("greedy", "random", name="m_rand", replays=1)
    finally:
        tactics_config.set_config(None)
    assert report["opponent_id"] == "random@schema2"
    assert report["fights"] >= 1                                    # бой реально сыгран
    # случайный соперник ходит легально: его предложения не правятся средой вне A(s)
    for row in report["rows"]:
        assert row["illegal_proposals"] == 0
