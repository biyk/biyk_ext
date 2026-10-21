# tests/test_arent_multiactor.py — мульти-акторная разметка (коммит №3 плана).
#
# Суть v2: размечаем НЕ одного героя, а каждого живого бойца нашей команды на его
# микро-шаге по инициативе. Проверяем инварианты: actor_ids отдаёт ровно команду src
# (без врагов и нейтральных), политики умеют pick() для ЛЮБОГО актёра (наведённого как
# src), observe с переданным порядком проставляет признаки инициативы (а без порядка —
# нет), а sample_one размечает союзника так же честно, как героя.
import pytest

from arent.dataset import sample_one
from arent.observe import observe, observe_payload
from arent.states import actor_ids, rebuild, src_candidates
from arent.teacher import pinned
from arent.teachers import get_teacher
from conftest import make_npc, make_scene_payload, make_weapon
from planner.context import BattleContext
from planner.initiative import team_actors
from planner.sim import Simulation
from arent import spec


@pytest.fixture
def team_scene():
    """Герой A + союзник C (та же диспозиция) против врага B; нейтральный D вне команды."""
    weapons = [make_weapon("sword", "Меч", damage="1d6+2", bonus=3, sure_ft=5)]
    hero = make_npc("A", 50, 150, disposition=-1, hp=10, speed=30, initiative=18)
    hero.update({"ac": 12, "toHit": 3, "weapons": weapons})
    ally = make_npc("C", 50, 250, disposition=-1, hp=10, speed=30, initiative=9)
    ally.update({"ac": 12, "toHit": 3, "weapons": weapons})
    foe = make_npc("B", 300, 150, disposition=1, hp=11, speed=30, initiative=14)
    foe.update({"ac": 16, "toHit": 3})
    neutral = make_npc("D", 50, 50, disposition=0, hp=1)
    payload = make_scene_payload(npcs=[hero, foe, ally, neutral], walls=[], weapons=weapons)
    payload.update({"src": "A", "token": "B", "speed": 30})
    return payload


#--- 1. actor_ids: кто реально ходит за нашу команду --------------------------
def test_actor_ids_lists_team_a_only(team_scene):
    assert set(actor_ids(team_scene)) == {"A", "C"}        # герой и союзник, без врага/нейтрального


def test_src_candidates_alias_actor_ids(team_scene):
    assert src_candidates(team_scene) == actor_ids(team_scene)


def test_actor_ids_drops_dead_hero(team_scene):
    hurt = rebuild(team_scene, "A", hp={"A": 0})
    assert "A" not in actor_ids(hurt)                       # мертвый src не ходит


#--- 2. порядок инициативы и команда в нём ------------------------------------
def test_initiative_order_is_deterministic_from_seed(team_scene):
    ctx = BattleContext.from_payload(team_scene)
    a = Simulation.of(ctx, env_seed=7).initiative_order
    b = Simulation.of(ctx, env_seed=7).initiative_order
    assert a == b and set(a) == {"A", "C", "B"}             # явные initiative 18/9/14 -> A,B,C


def test_explicit_initiative_beats_d20(team_scene):
    ctx = BattleContext.from_payload(team_scene)
    order = Simulation.of(ctx, env_seed=1).initiative_order
    assert order[0] == "A"                                  # uA=18 максимальная из явных


def test_team_actors_are_team_a_in_order(team_scene):
    ctx = BattleContext.from_payload(team_scene)
    sim = Simulation.of(ctx, env_seed=3)
    actors = team_actors(sim.units, ctx.src_id, sim.initiative_order)
    assert set(actors) == {"A", "C"}                        # B — враг, не наша команда


#--- 3. observe: признаки инициативы только когда передан порядок -------------
def test_observe_stamps_initiative_when_order_given(team_scene):
    ctx = BattleContext.from_payload(team_scene)
    order = Simulation.of(ctx, env_seed=5).initiative_order
    obs = observe(ctx, order, ctx.src_id)
    for e in obs["enemies"]:
        assert isinstance(e["initiativeIndex"], int) and e["initiativeIndex"] >= 0
        assert isinstance(e["isNextToAct"], bool)
    for a in obs["allies"]:
        assert isinstance(a["initiativeIndex"], int)
    assert 0.0 <= obs["me"]["alliesActedFraction"] <= 1.0


def test_observe_without_order_leaves_initiative_zero(team_scene):
    obs = observe_payload(team_scene)                        # ни order, ни actor
    assert "alliesActedFraction" not in obs["me"]
    assert all("initiativeIndex" not in e for e in obs["enemies"])


def test_acted_fraction_counts_earlier_team_a(team_scene):
    ctx = BattleContext.from_payload(team_scene)
    order = Simulation.of(ctx, env_seed=0).initiative_order  # A(18) > B(14) > C(9)
    last = team_actors({u.id: u for u in Simulation.of(ctx).units.values()},
                       ctx.src_id, order)[-1]
    obs = observe(rebuild_to_ctx(team_scene, last), order, last)
    if last == "C":                                          # до C успел сходить A -> доля > 0
        assert obs["me"]["alliesActedFraction"] > 0.0


def rebuild_to_ctx(payload, actor):
    return BattleContext.from_payload(rebuild(payload, actor))


#--- 4. teacher.pick работает для любого актёра -------------------------------
def test_pick_labels_any_team_actor(team_scene):
    with pinned(rounds=1, time_limit_sec=0.5):
        impl = get_teacher("greedy", rounds=1, time_limit_sec=0.5)
        for actor in actor_ids(team_scene):
            ctx = BattleContext.from_payload(rebuild(team_scene, actor))
            actions = impl.pick(ctx)
            assert isinstance(actions, list) and actions      # любой живой боец размечается


def test_pick_delegates_to_plan(team_scene):
    with pinned(rounds=1, time_limit_sec=0.5):
        impl = get_teacher("greedy", rounds=1, time_limit_sec=0.5)
        ctx = BattleContext.from_payload(team_scene)
        assert [a.to_dict() for a in impl.pick(ctx)] == [a.to_dict() for a in impl.plan(ctx)]


#--- 5. sample_one размечает союзника как src ---------------------------------
def test_sample_one_labels_ally_actor(team_scene):
    with pinned(rounds=1, time_limit_sec=0.5):
        impl = get_teacher("greedy", rounds=1, time_limit_sec=0.5)
        ally_payload = rebuild(team_scene, "C")
        order = Simulation.of(BattleContext.from_payload(ally_payload), env_seed=11).initiative_order
        sample, reason = sample_one("team", ally_payload, impl, {"src": "C", "variant": 0}, order)
    assert reason == "ok", reason
    assert sample["meta"]["src"] == "C"
    assert len(sample["state"]) == spec.dims()["state"]
