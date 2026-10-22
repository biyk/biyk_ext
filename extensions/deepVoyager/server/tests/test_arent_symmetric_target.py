# tests/test_arent_symmetric_target.py — честное зеркало: цель (=признак isTargeted)
# должна быть симметрична по seat, иначе наблюдение даёт src/hero нечестное преимущество.
#
# Корень: Simulation.context_for(unit_id) подставлял ГЛОБАЛЬНЫЙ self._target_id (изначальная
# цель героя = F1) для ЛЮБОГО актёра. Для hero-seat это враг → entity_slot ставит врагу
# isTargeted=1. Для foe-seat F1 цель=F1=он сам, которого нет в его списке врагов → врагу A1
# isTargeted=0. Toy-наблюдение: одна и та же модель над равными бойцами выигрывает всегда
# будучи hero и всегда проигрывает будучи foe (ranged self-play hero=1.0/foe=0.0).
#
# Правильно: наблюдение актёра другой команды обязано видеть помеченной СВОЮ цель (ближайшего
# живого врага), симметрично герою. Путь героя (BC/serving/parity) не трогаем — у него цель
# задаётся клиентом (payload.token) и остаётся как есть.
from playground import arena
from arent import scenarios
from arent.observe import observe
from planner.context import BattleContext
from planner.sim import Simulation


def _sim(name, raw):
    payload = arena.build_payload(raw, name)
    return Simulation.of(BattleContext.from_payload(payload))


#--- 1. цель актёра любой команды враждебна ЕМУ (не себе/союзнику) --------------
def test_context_for_target_is_hostile_to_every_actor():
    for cls in ("melee", "fast", "reach", "ranged"):
        for name, raw, _p in scenarios.generate_mirror_duels(cls, 3, seed=202):
            sim = _sim(name, raw)
            hero = sim.hero_id
            foe = next(uid for uid, u in sim.units.items() if u.hostile_to_hero)
            for actor in (hero, foe):
                ctx = sim.context_for(actor)
                hostiles = {t.id for t in ctx.hostile_targets()}
                assert ctx.target_id is not None, f"{name}/{cls}: {actor} без цели"
                assert ctx.target_id in hostiles, (
                    f"{name}/{cls}: актёр {actor} видит цель {ctx.target_id!r} "
                    f"не-врагом (asимметрия src/hero)")


#--- 2. признак isTargeted симметричен: оба seat помечают РОВНО одного врага ----
def test_is_targeted_count_equal_across_seats():
    for name, raw, _p in scenarios.generate_mirror_duels("ranged", 3, seed=202):
        sim = _sim(name, raw)
        hero = sim.hero_id
        foe = next(uid for uid, u in sim.units.items() if u.hostile_to_hero)

        def marked(actor):
            ctx = sim.context_for(actor)
            obs = observe(ctx, sim.initiative_order, actor)
            return sum(1 for e in obs["enemies"] if e["id"] == obs["target"])

        assert marked(hero) == 1, f"{name}: hero-seat не видит помеченной цель"
        assert marked(foe) == marked(hero), (
            f"{name}: isTargeted асимметричен по seat (hero=1, foe={marked(foe)})")


#--- 3. путь героя неизменен: явная клиентская цель остаётся -------------------
def test_hero_keeps_client_target():
    """BC/serving одиночного героя: context_for(hero) обязан вернуть payload.token как цель."""
    for name, raw, _p in scenarios.generate_mirror_duels("ranged", 2, seed=202):
        payload = arena.build_payload(raw, name)
        base = BattleContext.from_payload(payload)
        sim = Simulation.of(base)
        hero = base.src_id
        client_target = base.target_id
        ctx = sim.context_for(hero)
        if client_target is not None and sim.units.get(client_target) \
                and sim.units[client_target].is_alive:
            assert ctx.target_id == client_target, "герой потерял явно выбранную цель"
