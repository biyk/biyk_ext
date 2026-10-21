# tests/test_arent_universal_soldier.py — WP1 «Универсальный солдат»: симметричная генерация.
#
# Новый контракт состава: НИКАКОГО специального блока hero/captain на одной стороне.
# Обе команды набираются симметрично из одного пула ролей и одного пула арсеналов;
# у КАЖДОГО токена явно заданы initiative, hp, speed и weapons (арсенал записи формата
# arena), как в ho2_*. Провераем:
#   1) симметрия составов и равные права сторон (одинаковые пулы классов/арсеналов);
#   2) каждый токен самодостаточен: initiative/hp/speed/weapons на месте;
#   3) паритета нет: первый токен не жирнее остальных по hp/арсеналу;
#   4) arena.build_payload работает без raw["hero"]: src = первый токен, его оружие;
#   5) детерминизм seed сохраняет симметрию (тот же бой = тот же состав).
from arent import scenarios
from playground import arena


def _pool(count=24, seed=5, random_start=None):
    return scenarios.generate(count, seed, random_start=random_start)


def _side(raw, disp):
    return [t for t in raw["tokens"] if t["disposition"] == disp]


#--- 1-3. симметрия состава и самодостаточность токенов -----------------------
def test_teams_are_symmetric_in_size_for_every_scenario():
    scen = _pool(count=30, seed=11)
    assert scen, "генератор не выдал сценариев"
    for name, raw, params in scen:
        ours, theirs = _side(raw, -1), _side(raw, 1)
        assert len(ours) == len(theirs), f"{name}: составы несимметричны"
        assert params["n_allies"] == params["n_foes"] == len(ours)


def test_every_token_has_initiative_stats_and_own_weapons():
    for name, raw, _p in _pool(count=30, seed=11):
        assert "hero" not in raw, f"{name}: остался специальный блок hero"
        for tok in raw["tokens"]:
            assert tok.get("initiative") and 1 <= tok["initiative"] <= 30, f"{name}:{tok['id']}"
            assert tok.get("hp") and tok.get("speed") and tok.get("damage"), f"{name}:{tok['id']}"
            weapons = tok.get("weapons")
            assert weapons and all(w.get("id") and w.get("damage") for w in weapons), \
                f"{name}:{tok['id']}: у токена нет своего арсенала"


def test_arsenal_and_class_pools_are_shared_between_sides():
    scen = _pool(count=40, seed=21)
    a_ars = {tuple(sorted(w["id"] for w in t["weapons"]))
             for _n, raw, _p in scen for t in _side(raw, -1)}
    b_ars = {tuple(sorted(w["id"] for w in t["weapons"]))
             for _n, raw, _p in scen for t in _side(raw, 1)}
    classes = {c for _n, _r, p in scen for c in p["side_a_classes"]} | \
              {c for _n, _r, p in scen for c in p["side_b_classes"]}
    assert a_ars & b_ars, "сторона A и сторона B вооружаются из непересекающихся пулов"
    assert classes >= {"melee", "ranged"} or len(classes) >= 3, "классы однообразны"


def test_no_side_gets_a_fatter_lead_token():
    """Бывший «капитан» больше не эксклюзив: hp-диапазон и арсенал одинаковы для всех."""
    for name, raw, _p in _pool(count=30, seed=7):
        for disp in (-1, 1):
            toks = _side(raw, disp)
            hps = [t["hp"] for t in toks]
            assert max(hps) - min(hps) <= 45 - 6, f"{name}: диапазон hp не из общего пула"
            lead, rest = toks[0], toks[1:]
            assert all(len(t["weapons"]) >= len(lead["weapons"]) - 1 for t in rest) or not rest


#--- 4. разбор без hero-блока --------------------------------------------------
def test_build_payload_without_hero_block_defaults_to_first_token():
    raw = dict(scenarios.build(1, 42, random_start=False)[1])
    raw.pop("hero", None)
    payload = arena.build_payload(raw, "gen_sym_probe")
    first = raw["tokens"][0]
    assert payload["src"] == first["id"]
    assert payload["weapons"] == first["weapons"]
    assert payload["speed"] == first["speed"]
    npcs = {n["id"]: n for n in payload["data"]["npcs"]}
    assert all("weapons" in n and n["weapons"] for n in npcs.values())


def test_build_payload_legacy_hero_block_still_works():
    """Старые арены (ho_*, hero-блок) продолжают работать: hero задаёт src и оружие."""
    raw = {"hero": {"id": "A", "speed": 30, "weapons": [{"id": "s", "name": "меч",
            "damage": "1d6", "attackBonus": 2, "sureFt": 5, "doubtFt": 5}]},
           "tokens": [{"id": "A", "cell": [1, 1], "hp": 10, "disposition": -1},
                      {"id": "B", "cell": [5, 5], "hp": 10, "disposition": 1}]}
    payload = arena.build_payload(raw, "legacy_probe")
    assert payload["src"] == "A" and payload["speed"] == 30


#--- 5. детерминизм: тот же seed -> тот же симметричный бой -------------------
def test_symmetry_is_deterministic_per_seed():
    a = [(n, str(sorted((t["id"], t["initiative"], t["hp"]) for t in r["tokens"])))
         for n, r, _p in scenarios.generate(8, 3)]
    b = [(n, str(sorted((t["id"], t["initiative"], t["hp"]) for t in r["tokens"])))
         for n, r, _p in scenarios.generate(8, 3)]
    assert a == b
