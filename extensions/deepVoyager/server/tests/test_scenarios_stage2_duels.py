# tests/test_scenarios_stage2_duels.py — дуэли Этапа 2: зеркало по классу + асимметрия (тот же tier).
#
# teaching_plan §Этап 2: 1v1 зеркальные по классу (melee×melee, fast×fast, reach×reach,
# ranged×ranged) плюс асимметричная пара ranged×melee (первый «тактический люфт» — гейт против
# рандомайзера). build() фиксит ОДНУ ось classes на обе стороны — для асимметрии нужны
# раздельные foe_classes/foe_arsenals. Имена пулов не должны коллидовать между профилями
# (разные классы -> разные group_id), иначе split по группам смешает сцены.
from playground import arena
from arent import scenarios

MELEE_ARSENALS = {"sword", "greatsword", "two_melee"}


def _sure(token):
    return [w["sureFt"] for w in token["weapons"]]


def _side_tokens(raw, prefix):
    return [t for t in raw["tokens"] if t["id"].startswith(prefix)]


#--- 1. зеркальные дуэли: обе стороны одного класса, оружие по профилю --------
def test_mirror_duels_are_class_symmetric():
    for cls in ("melee", "fast", "reach", "ranged"):
        pool = scenarios.generate_mirror_duels(cls, 6, seed=101)
        assert len(pool) == 6, f"{cls}: не добрал до count"
        for name, raw, p in pool:
            assert p["side_a_classes"] == [cls] == p["side_b_classes"]
            assert p["n_allies"] == 1 and p["n_foes"] == 1
            assert p["n_walls"] == 0 and p["layout"] == "structured"
            assert name.startswith(f"s2_{cls}_")
        ranged = cls == "ranged"
        for _n, raw, _p in pool:
            for tok in raw["tokens"]:
                if ranged:
                    assert max(_sure(tok)) > 5, f"{cls}: ожидается дальнобойное оружие"
                else:
                    assert max(_sure(tok)) <= 5, f"{cls}: не ближний бой в melee/fast/reach"


#--- 2. асимметрия ranged×melee: разные классы/оружие по сторонам -------------
def test_asym_duels_ranged_vs_melee_are_side_specific():
    pool = scenarios.generate_asym_duels("ranged", "melee", 6, seed=7)
    assert len(pool) == 6
    for name, raw, p in pool:
        assert p["side_a_classes"] == ["ranged"] and p["side_b_classes"] == ["melee"]
        assert name.startswith("s2_rangedvmelee_")
        for t in _side_tokens(raw, "A"):
            assert max(_sure(t)) > 5                    # стрелок бьёт издалека
        for t in _side_tokens(raw, "F"):
            assert max(_sure(t)) <= 5                    # милишник — в ближнем бою


#--- 3. валидность боёв из явного пула (hostile targets, src alive) -----------
def test_stage2_pools_are_valid_fights():
    for name, raw, _p in scenarios.generate_mirror_duels("ranged", 4, seed=3):
        payload = arena.build_payload(raw, name)
        ctx = scenarios._bc(payload)
        assert ctx.hostile_targets() and ctx.src.is_alive and payload.get("weapons")


#--- 4. имена не пересекаются между профилями (disjoint group ids) ------------
def test_names_do_not_collide_across_profiles():
    mirror = {n for c in ("melee", "fast", "reach", "ranged")
              for n, _r, _p in scenarios.generate_mirror_duels(c, 5, seed=50)}
    asym = {n for n, _r, _p in scenarios.generate_asym_duels("ranged", "melee", 5, seed=50)}
    assert mirror and asym
    assert not (mirror & asym), "group_id зеркального и асимметричного пулов пересеклись"


#--- 5. детерминизм по seed ----------------------------------------------------
def test_mirror_duels_deterministic_for_a_seed():
    a = scenarios.generate_mirror_duels("reach", 5, seed=9)
    b = scenarios.generate_mirror_duels("reach", 5, seed=9)
    assert [x[0] for x in a] == [x[0] for x in b]
    assert [str(sorted(x[2].items())) for x in a] == [str(sorted(x[2].items())) for x in b]


#--- 6. зеркало = РАВНЫЕ бойцы: одинаковые статы и оружие по обе стороны -------
# src/hero-перевес в ранней оценке был артефактом незеркальных составов: make_unit тянул
# hp/damage/hitChance независимо для A и B, поэтому «зеркало» был нечестным зеркалом.
# Правильное зеркало Этапа 2: сторона B = копия стороны A (те же hp/speed/damage/reach/
# hitChance/initiative и тот же арсенал), различаются лишь id/disposition/позиция.
def test_mirror_duels_are_equal_armed():
    for cls in ("melee", "fast", "reach", "ranged"):
        for name, raw, p in scenarios.generate_mirror_duels(cls, 6, seed=202):
            assert p["side_a_stats"] == p["side_b_stats"], f"{name}: статы сторон различаются"
            assert p["side_a_arsenals"] == p["side_b_arsenals"], f"{name}: оружие сторон различное"
            ia = _side_tokens(raw, "A")[0]
            ib = _side_tokens(raw, "F")[0]
            for key in ("hp", "speed", "damage", "reachFt", "hitChance", "initiative"):
                assert ia[key] == ib[key], f"{name}: {key} не зеркален"


#--- 7. асимметрия НЕ равняет стороны (разные классы по замыслу) ----------------
def test_asym_duels_are_not_equal_armed():
    for name, raw, p in scenarios.generate_asym_duels("ranged", "melee", 4, seed=8):
        assert p["side_a_classes"] != p["side_b_classes"]
        assert p["side_a_arsenals"] != p["side_b_arsenals"]
