# tests/test_arent_team_credit.py — WP4: командный credit assignment.
#
# Контракты: (1) use_team_reward=True — дефолт RL-контура; (2) терминальный исход
# доставляется КАЖДОМУ шагу каждого актёра через общий GAE-хвост (смена актёра не рвёт
# цепочку); (3) на командном пути death_penalty не участвует — гибель оценивается только
# через вклад в исход: «пожертвовал собой -> команда победила» даёт положительный
# адвантейдж; (4) окно пата в полиакторной среде тикает по РАУНДАМ (полный цикл
# инициативы), а не по ходам актёров, и события внутри раунда сбрасывают пат.
from arent.cli import parser
from arent.polyenv import PolyFightEnv
from arent.rollout import RlConfig, gae
from arent.team_reward import WIN, TeamReward
from conftest import make_npc, make_scene_payload, make_weapon
from planner.initiative import Unit

NOTHING = {"cell": 0, "target": -1, "weapon": -1}
ATTACK = {"cell": 0, "target": 0, "weapon": 0}


def _npc(nid, col, disp, hp, ini):
    return make_npc(nid, col * 50, 0, disposition=disp, hp=hp, speed=30, initiative=ini)


def _scene_sacrifice():
    """A1(hp3) F1(hp6, меч) A2 — F1 дважды бьёт A1 насмерть, A2 добивает F1: WIN после жертвы."""
    a1, f1, a2 = _npc("A1", 0, -1, 3, 20), _npc("F1", 1, 1, 6, 15), _npc("A2", 2, -1, 30, 5)
    f1["weapons"] = [make_weapon("fsword", "меч", damage="1d6", sure_ft=5)]
    payload = make_scene_payload(npcs=[a1, f1, a2],
                                 weapons=[make_weapon("sword", damage="1d6+2")])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


def _scene_stall():
    a1, a2 = _npc("A1", 0, -1, 30, 20), _npc("A2", 2, -1, 30, 5)
    f1, f2 = _npc("F1", 8, 1, 30, 15), _npc("F2", 9, 1, 30, 10)
    payload = make_scene_payload(npcs=[a1, a2, f1, f2],
                                 weapons=[make_weapon("sword", damage="1d6+2")])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


def _scene_events():
    """Долгий бой с регулярными попаданиями: ни один раунд не тихий, смерть не близка."""
    a1, f1, a2 = _npc("A1", 0, -1, 100, 20), _npc("F1", 1, 1, 100, 15), _npc("A2", 2, -1, 100, 5)
    f1["weapons"] = [make_weapon("fsword", "меч", damage="1d6", sure_ft=5)]
    payload = make_scene_payload(npcs=[a1, f1, a2],
                                 weapons=[make_weapon("sword", damage="1d6+2")])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


#--- 1. командная награда — дефолт ---------------------------------------------
def test_rl_config_defaults_to_team_reward_and_polyactor():
    cfg = RlConfig()
    assert cfg.use_team_reward is True                  # универсальный солдат по умолчанию
    assert cfg.polyactor is True


def test_cli_rl_flags_are_tristate_so_defaults_survive():
    ns = parser().parse_args(["rl"])                     # без флагов: None = не трогать дефолты
    assert ns.team_reward is None and ns.polyactor is None
    assert parser().parse_args(["rl", "--no-team-reward"]).team_reward is False
    assert parser().parse_args(["rl", "--mono-actor"]).polyactor is False


#--- 2. GAE-хвост доходит до всех актёров --------------------------------------
def test_terminal_outcome_reaches_every_step_across_actor_switches():
    rewards, values = [0.0, 0.0, 5.0], [0.0, 0.0, 0.0]
    adv, _ret = gae(rewards, values, [0.0, 0.0, 0.0], [1, 1, 0], gamma=0.98, lam=0.95)
    assert adv[0] > 0 and adv[1] > 0                    # смена актёра не обрывает цепочку


def test_sacrifice_then_win_gives_positive_advantage_to_the_dead_unit():
    e = PolyFightEnv(rounds_cap=8, death_penalty=-100.0, team=TeamReward())
    e.reset(_scene_sacrifice())
    rewards, actors, died_mid = [], [], None
    info = {}
    for _ in range(6):
        actor = e.actor
        # жертва A1 выжидает, остальные (и свои, и враги) бьют ближайшую цель
        _n, r, terminated, _tr, info = e.step(NOTHING if actor == "A1" else ATTACK)
        rewards.append(r)
        actors.append(actor)
        if not info["survived"] and died_mid is None:
            died_mid = len(rewards) - 1                  # шаг, на котором якорь погиб
        if terminated:
            break
    assert died_mid is not None and info["outcome"] == "win"
    adv, _ret = gae(rewards, [0.0] * len(rewards), [0.0] * len(rewards),
                    [1] * (len(rewards) - 1) + [0], gamma=0.98, lam=0.95)
    dead_steps = [i for i, a in enumerate(actors) if a == "A1"]
    assert all(adv[i] > 0 for i in dead_steps)          # погиб, команда выиграла -> плюс
    assert all(adv[i] > 0 for i in range(len(adv)))     # и всем остальным тоже


#--- 3. death_penalty вне командного пути ---------------------------------------
def test_death_penalty_argument_does_not_touch_team_path_rewards():
    def trace(pen):
        e = PolyFightEnv(rounds_cap=8, death_penalty=pen, team=TeamReward())
        e.reset(_scene_sacrifice())
        out = []
        for _ in range(6):
            _n, r, terminated, _tr, info = e.step(ATTACK if e.actor.startswith("F") else NOTHING)
            out.append(round(r, 6))
            if terminated:
                break
        return out
    assert trace(0.0) == trace(-100.0)                  # исход LOSS/WIN задаёт TeamReward
    dead_a = Unit("A", (0, 0), 0.0, 6, 5, 1, .65, False)
    live_b = Unit("B", (1, 0), 20.0, 6, 5, 1, .65, True)
    tr = TeamReward().step({"A": dead_a}, {"A": dead_a, "B": live_b}, "A")
    assert tr[1] == "loss" and tr[0] < 0                # минус LOSS, без отдельного штрафа за смерть


#--- 4. окно пата тикает раундами, события раунда копятся -----------------------
def test_draw_counts_rounds_not_actor_turns_in_polyactor_env():
    e = PolyFightEnv(rounds_cap=20, team=TeamReward(draw_window=2))
    e.reset(_scene_stall())                             # 4 актёра: раунд = 4 шага
    results = [e.step(NOTHING) for _ in range(7)]       # раунд 1 + 3 хода раунда 2
    assert [t for _n, _r, t, _tr, _i in results] == [False] * 7
    _n, _r, terminated, _tr, info = e.step(NOTHING)     # 8-й шаг закрывает раунд 2 -> пат
    assert terminated is True and info["outcome"] == "draw"


def test_eventful_round_does_not_start_the_stall_clock():
    """Раунд с попаданием — событие; пат считается только после draw_window ТИХИХ раундов."""
    e = PolyFightEnv(rounds_cap=20, team=TeamReward(draw_window=2))
    e.reset(_scene_events())                             # F1 бьёт A1 каждый свой ход = событие
    terminated = False
    for _ in range(8):                                   # больше draw_window полных раундов
        _n, _r, terminated, _tr, _i = e.step(ATTACK if e.actor.startswith("F") else NOTHING)
        if terminated:
            break
    assert not terminated                                # события не дают накопить тихое окно


def test_win_reward_scale_dominates_dense_terms():
    tr = TeamReward()
    prev = {"A": Unit("A", (0, 0), 20.0, 6, 5, 1, .65, False),
            "B": Unit("B", (1, 0), 1.0, 6, 5, 1, .65, True)}
    nxt = {"A": Unit("A", (0, 0), 20.0, 6, 5, 1, .65, False),
           "B": Unit("B", (1, 0), 0.0, 6, 5, 1, .65, True)}
    reward, outcome = tr.step(prev, nxt, "A")
    assert outcome == "win" and reward > WIN - 1.0      # ±5 исход, плотные мелкие не перебивают
