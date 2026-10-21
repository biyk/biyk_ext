# tests/test_arent_per_actor_view.py — WP2: наблюдение от ЛЮБОГО актёра (viewpoint).
#
# «Универсальный солдат»: один и тот же бой, снятый с точки зрения разных юнитов,
# даёт РАЗНЫЕ, но валидные наблюдения фиксированной схемы (spec.SCHEMA, dims()).
# Ключевое: ctx.src_id — текущий актёр, а не капитан; оружие и скорость — его собственные
# (per-token weapons из npcs[]), для старых сцен без них — откат на базу (совместимость).
# Лимиты: K_ALLIES=6 / K_TARGETS=8 выдерживают зеркальный состав 6 на 6 без роста сети.
from arent import spec
from arent.encode import observation, state
from arent.observe import observe
from arent.slots import build
from conftest import make_npc, make_scene_payload, make_weapon
from planner.context import BattleContext
from planner.sim import Simulation


def _arsenal(tag, sure=5):
    return [make_weapon(f"{tag}s", "меч", damage="1d6+2", bonus=3, sure_ft=sure),
            make_weapon(f"{tag}b", "лук", damage="1d8", bonus=2, sure_ft=30, doubt_ft=120)]


def _symmetric_scene():
    """Симметричный бой 2 на 2: у каждого токена своё оружие, инициатива, скорость."""
    a1 = make_npc("A1", 50, 50, disposition=-1, hp=20, speed=30, initiative=15)
    a1["weapons"] = _arsenal("a1")
    a2 = make_npc("A2", 50, 150, disposition=-1, hp=14, speed=40, initiative=10)
    a2["weapons"] = _arsenal("a2", sure=30)
    f1 = make_npc("F1", 350, 50, disposition=1, hp=16, speed=30, initiative=12)
    f1["weapons"] = _arsenal("f1")
    f2 = make_npc("F2", 350, 150, disposition=1, hp=12, speed=20, initiative=8)
    f2["weapons"] = _arsenal("f2")
    payload = make_scene_payload(npcs=[a1, a2, f1, f2], weapons=a1["weapons"])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    return payload


def _view(payload, actor):
    """Наблюдение актора от его лица: src + его оружие/скорость через context_for."""
    sim = Simulation.of(BattleContext.from_payload(payload))
    ctx = sim.context_for(actor)
    obs = observe(ctx, sim.initiative_order, actor)
    return ctx, observation(ctx, obs, build(ctx, obs))


#--- 1. viewpoint: любой живой токен — полноценный актёр ----------------------
def test_same_fight_gives_distinct_valid_views_per_actor():
    payload = _symmetric_scene()
    views = {}
    for actor in ("A1", "A2", "F1", "F2"):
        ctx, vec = _view(payload, actor)
        assert vec["schema"] == spec.SCHEMA
        assert len(vec["state"]) == spec.dims()["state"]
        assert ctx.src_id == actor
        views[actor] = vec["state"]
    assert views["A1"] != views["F1"]                       # разные лица — разные векторы
    assert views["A1"] != views["A2"]


def test_actor_view_uses_own_weapons_not_bases():
    payload = _symmetric_scene()
    ctx_a2, _v = _view(payload, "A2")
    ids = {w.id for w in ctx_a2.weapons}
    assert ids == {"a2s", "a2b"}, "a2 видит чужой арсенал вместо своего"


def test_actor_view_falls_back_to_base_weapons_for_legacy_tokens():
    """Старые сцены (ho_*): у токенов нет weapons — откат на базовый арсенал без падения."""
    hero = make_npc("A", 50, 50, disposition=-1, hp=20, speed=30)
    foe = make_npc("B", 250, 50, disposition=1, hp=20, speed=30)
    payload = make_scene_payload(npcs=[hero, foe], weapons=_arsenal("base"))
    payload.update({"src": "A", "token": "B", "speed": 30})
    ctx, vec = _view(payload, "A")
    assert {w.id for w in ctx.weapons} == {"bases", "baseb"}
    assert len(vec["state"]) == spec.dims()["state"]


def test_context_for_reports_actor_speed_steps():
    payload = _symmetric_scene()
    sim = Simulation.of(BattleContext.from_payload(payload))
    assert sim.context_for("A2").speed_steps == 40 // spec_d_scale_feet()  # 40 ft / 5 ft
    assert sim.context_for("A1").speed_steps == 30 // 5


def spec_d_scale_feet():
    from planner.points import tuning
    return int(tuning().feet_per_cell)


#--- 2. лимиты слотов: зеркальный состав 6 на 6 влезает -----------------------
def test_six_versus_six_fits_into_k_limits():
    tokens, actors = [], ("A1", "A2", "A3", "A4", "A5", "A6")
    for i, uid in enumerate(actors):
        tok = make_npc(uid, 50 + 50 * (i % 3), 50, disposition=-1, hp=20, speed=30,
                       initiative=20 - i)
        tok["weapons"] = _arsenal(uid.lower())
        tokens.append(tok)
    for i in range(6):
        tok = make_npc(f"F{i + 1}", 450 + 50 * (i % 3), 250, disposition=1, hp=20,
                       speed=30, initiative=10 - i)
        tok["weapons"] = _arsenal(f"f{i + 1}")
        tokens.append(tok)
    payload = make_scene_payload(npcs=tokens, weapons=tokens[0]["weapons"])
    payload.update({"src": "A1", "token": "F1", "speed": 30})
    ctx, vec = _view(payload, "A1")
    obs = observe(ctx, Simulation.of(BattleContext.from_payload(payload)).initiative_order, "A1")
    assert len(obs["allies"]) <= spec.K_ALLIES              # 5 союзников < 6 — все видны
    assert len(obs["enemies"]) <= spec.K_TARGETS            # 6 врагов < 8 — все видны
    assert len(vec["state"]) == spec.dims()["state"]
