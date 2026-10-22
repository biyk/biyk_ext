# tests/test_scenarios_duel_filter.py — фильтрованная генерация дуэлей (teaching_plan §Этап 1).
#
# Этап 1 требует узкий класс арен: архетип duel, ТОЛЬКО melee×2, n_side=1 (дуэль 1v1),
# поле БЕЗ стен (wall_profile=open), structured-расстановка (честный A/B на идентичном
# старте). Существующий build() всё рандомит и фильтров не знает — добавляем именованные
# overrides + обёртку generate_duels. Проверяем, что override реально фиксирует каждую ось,
# пул остаётся валидным боем и детерминирован по seed (учитель и политика видят один старт).
from playground import arena
from arent import scenarios

MELEE_ARSENALS = {"sword", "greatsword", "two_melee"}


def _duel_raw_params(seq=3, seed=99):
    return scenarios.build(seq, seed, random_start=False, archetype="duel",
                           classes=["melee"], arsenals=tuple(sorted(MELEE_ARSENALS)),
                           n_side=1, wall_profile="open", field_profile="small")


#--- 1. build() честно применяет все overrides -------------------------------
def test_build_honors_every_override_axis():
    name, raw, p = _duel_raw_params()
    assert name.startswith("gen_duel_")
    assert p["archetype"] == "duel"
    assert p["n_allies"] == 1 and p["n_foes"] == 1          # n_side=1 зеркально
    assert p["side_a_classes"] == ["melee"]                  # classes=["melee"] на обе стороны
    assert p["side_b_classes"] == ["melee"]
    assert p["wall_profile"] == "open" and p["n_walls"] == 0  # поле без стен
    assert p["field_profile"] == "small"
    assert p["layout"] == "structured"                       # random_start=False -> канон
    assert set(p["side_a_arsenals"]) <= MELEE_ARSENALS       # только ближний бой
    assert set(p["side_b_arsenals"]) <= MELEE_ARSENALS
    assert len(raw["tokens"]) == 2                           # ровно двое: 1 на 1


#--- 2. все вооружения ближние (sureFt <= 5) ---------------------------------
def test_duel_weapons_are_all_melee():
    _name, raw, _p = _duel_raw_params(seq=1, seed=7)
    for tok in raw["tokens"]:
        for w in tok["weapons"]:
            assert w["sureFt"] <= 5, f"{tok['id']}: дальнобойное оружие в melee-дуэли"


#--- 3. generate_duels: форма, валидность, уникальность ----------------------
def test_generate_duels_is_valid_uniform_pool():
    pool = scenarios.generate_duels(12, seed=202)
    assert len(pool) == 12, "generate_duels не добрал до count"
    names = [n for n, _r, _p in pool]
    assert len(set(names)) == len(names), "имена дуэлей не уникальны"
    for name, raw, p in pool:
        assert p["archetype"] == "duel" and p["n_foes"] == 1
        assert p["side_a_classes"] == ["melee"] == p["side_b_classes"]
        assert p["n_walls"] == 0
        payload = arena.build_payload(raw, name)
        ctx = scenarios._bc(payload)
        assert ctx.hostile_targets(), f"{name}: нет кого бить"
        assert ctx.src.is_alive and payload.get("weapons")


#--- 4. детерминизм по seed (честный A/B) -----------------------------------
def test_generate_duels_is_deterministic_for_a_seed():
    a = [(n, str(sorted(p.items()))) for n, _r, p in scenarios.generate_duels(6, seed=42)]
    b = [(n, str(sorted(p.items()))) for n, _r, p in scenarios.generate_duels(6, seed=42)]
    assert a == b


#--- 5. разные seed -> разные бои (stats/позиции не зафиксированы) -----------
def test_generate_duels_varies_across_seeds():
    def sig(seed):
        return tuple(((tuple(t["cell"]), t["hp"]) for _n, raw, _p
                      in scenarios.generate_duels(5, seed=seed) for t in raw["tokens"]))
    assert sig(1) != sig(2), "duel-пул не меняется от seed к seed"
