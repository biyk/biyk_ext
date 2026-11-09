# tests/test_arent_scenario_maneuvers.py — Этап 5: раздать юнитам манёвры (голова обучема).
#
# Проверяем СКВОЗНОЙ поток данных манёвров, а не механику сима (она в test_action_economy_sim):
#   1) порядок MANEUVER_ITEMS = spec5.MANEUVER_KINDS (индекс слота maneuver-головы детерминирован);
#   2) stage43 (canon+pool) раздаёт каждому бойцу обеих сторон 3 предмета (честный A/B-симметрия);
#   3) arena.build_payload несёт манёвры и на npc (пер-токен, для сима) и на верхний payload
#      (от лица актёра, для play/учителя);
#   4) Token.maneuver_kinds парсится из npcs[] -> Simulation.of поднимает его у ОБЕИХ сторон ->
#      use_action(реальным itemId) списывает действие/поднимает флаг (голова живая, не мёртвая);
#   5) обратная совместимость: арены без maneuvers (v2/v3/v4, ho_*) -> maneuver_items/
#      maneuver_kinds пусты -> прежний бит-в-бит путь; build без флага не раздаёт манёвры.
from conftest import make_npc, make_scene_payload, make_weapon
from playground import arena
from planner.context import BattleContext
from planner.action import use_action
from planner.payload import parse_maneuver_kinds, parse_tokens
from planner.sim import Simulation
from arent import scenarios, spec5
from arent.scenario_units import MANEUVER_ITEMS

KIND_ORDER = tuple(m["kind"] for m in MANEUVER_ITEMS)
ID_ORDER = tuple(m["id"] for m in MANEUVER_ITEMS)


#--- 1. реестр и порядок ────────────────────────────────────────────────────────────
def test_maneuver_items_order_matches_spec():
    # индекс слота maneuver-головы (serve==train) задан порядком реестра == spec5.MANEUVER_KINDS
    assert KIND_ORDER == spec5.MANEUVER_KINDS == ("dash", "disengage", "dodge")
    assert len({m["id"] for m in MANEUVER_ITEMS}) == len(MANEUVER_ITEMS)   # id уникальны
    assert all(m.get("name") for m in MANEUVER_ITEMS)


#--- 2. полигон stage43 раздаёт манёвры обеим сторонам ──────────────────────────────
def _assert_tokens_carry_maneuvers(raw):
    tokens = raw["tokens"]
    assert tokens, "нет токенов"
    for tok in tokens:
        mans = tok.get("maneuvers")
        assert mans is not None, f"токен {tok['id']} без манёвров"
        assert tuple(m["kind"] for m in mans) == KIND_ORDER   # фикс. порядок
        assert tuple(m["id"] for m in mans) == ID_ORDER       # реальные itemId FVTT


def test_stage43_canon_units_carry_maneuvers():
    pool = scenarios.generate_stage43_canon(2, seed=2026)
    assert pool
    for name, raw, params in pool:
        assert params["with_maneuvers"] is True, f"{name}: флаг манёвров не поднят"
        _assert_tokens_carry_maneuvers(raw)


def test_stage43_pool_units_carry_maneuvers():
    pool = scenarios.generate_stage43_pool(1, seed=404)
    assert pool
    for name, raw, params in pool:
        assert params["with_maneuvers"] is True, f"{name}: флаг манёвров не поднят"
        _assert_tokens_carry_maneuvers(raw)


#--- 3. build_payload: npc (пер-токен) + верхний уровень (актёр) ────────────────────
def test_build_payload_carries_maneuvers_per_npc_and_actor():
    name, raw, _p = scenarios.generate_stage43_canon(1, seed=7)[0]
    payload = arena.build_payload(raw, name)
    assert tuple(m["kind"] for m in payload["maneuvers"]) == KIND_ORDER   # с лица актёра
    # у КАЖДОГО npc свой набор (пер-токен: «универсальный солдат» ходит от лица любого)
    npcs = payload["data"]["npcs"]
    assert len(npcs) >= 2
    for n in npcs:
        assert tuple(m["kind"] for m in n["maneuvers"]) == KIND_ORDER


#--- 4. Token.maneuver_kinds -> Simulation.of -> исполнение через payload ───────────
def _two_side_payload():
    """A(-1) и B(1): каждому по три манёвра (реальные itemId) + оружие; src=A."""
    a = make_npc("A", 0, 0, disposition=-1, hp=40, damage="1d8")
    b = make_npc("B", 50, 0, disposition=1, hp=40, damage="1d8")
    for n in (a, b):
        n["maneuvers"] = [dict(m) for m in MANEUVER_ITEMS]
    return {**make_scene_payload(npcs=[a, b], weapons=[make_weapon("sword", damage="1d6+2")]),
            "speed": 30, "token": "B", "maneuvers": [dict(m) for m in MANEUVER_ITEMS]}


def test_token_parses_maneuver_kinds_from_npcs():
    ctx = BattleContext.from_payload(_two_side_payload())
    for tok in ctx.tokens:
        assert tok.maneuver_kinds == dict(zip(ID_ORDER, KIND_ORDER))
    # актёр видит предметы на верхнем уровне (для учителя/play)
    assert tuple(m["kind"] for m in ctx.maneuver_items) == KIND_ORDER


def test_simulation_of_populates_both_sides():
    sim = Simulation.of(BattleContext.from_payload(_two_side_payload()))
    expected = dict(zip(ID_ORDER, KIND_ORDER))
    # обе команды получают maneuver_kinds -> maneuver-голова обучема симметрично (честный A/B)
    assert sim.units["A"].maneuver_kinds == expected
    assert sim.units["B"].maneuver_kinds == expected


def test_maneuver_use_flows_through_payload_path():
    # без replace(): itemId из payload -> sim разбирает kind и исполняет манёвр (Уклонение)
    sim = Simulation.of(BattleContext.from_payload(_two_side_payload()))
    dodge_id = next(m["id"] for m in MANEUVER_ITEMS if m["kind"] == "dodge")
    after = sim.apply_actor_seq("A", [use_action(dodge_id)], reactions=True)
    assert after.units["A"].dodging is True
    assert after.units["A"].action == 0          # действие списано манёвром


#--- 5. обратная совместимость v2/v3/v4 и готовые арены ─────────────────────────────
def test_legacy_scene_has_no_maneuvers():
    p = make_scene_payload(npcs=[make_npc("A", 0, 0, disposition=-1),
                                 make_npc("B", 450, 0, disposition=1, damage="1d8")],
                           weapons=[make_weapon("sword")])
    ctx = BattleContext.from_payload(p)
    assert ctx.maneuver_items == ()
    assert all(t.maneuver_kinds == {} for t in ctx.tokens)   # sim: maneuvers не в обороте


def test_parse_maneuver_kinds_robust_to_garbage():
    assert parse_maneuver_kinds(None) == {}
    assert parse_maneuver_kinds("не список") == {}
    assert parse_maneuver_kinds([{"id": "x"}, {"kind": "dash"}, 5]) == {}   # мусор отброшен
    assert parse_maneuver_kinds([{"id": "d", "kind": "dash"}]) == {"d": "dash"}


def test_build_without_flag_attaches_no_maneuvers():
    # v2/v3/v4-профиль (duel, без with_maneuvers): токены чистые, голова не активна
    _name, raw, params = scenarios.build(1, seed=5, random_start=False, archetype="duel",
                                         classes=["melee"], arsenals=list(scenarios.DUEL_ARSENALS),
                                         n_side=1, wall_profile="open", field_profile="small")
    assert params["with_maneuvers"] is False
    assert all("maneuvers" not in tok for tok in raw["tokens"])
    payload = arena.build_payload(raw, _name)
    assert payload["maneuvers"] == []
    assert parse_tokens(payload["data"])[0].maneuver_kinds == {}
