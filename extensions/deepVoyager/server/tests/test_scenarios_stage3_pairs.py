# tests/test_scenarios_stage3_pairs.py — Этап 3: неравные дуэли 1v1 (асимметричные классы).
#
# teaching_plan §Этап 3: ranged×melee, reach×fast, tank×melee и т.п. — модель обязана играть
# ОТ КЛАССА, а не по шаблону. §1.9 (симметрия условий): чтобы сравнение было честным, каждая
# unordered-пара генерируется В ОБЕИХ перестановках состава — (A=a,B=b) и (A=b,B=a). Тогда у
# каждого класса одинаковое число боёв и на «своей» A-зоне, и на B-зоне, и ни один класс не
# сидет структурно в выгодной геометрии. Имена s3_* не должны коллидовать с s2_* (split по
# группам). Состав асимметричен по замыслу — стороны НЕ равны по статам/классу.
from playground import arena
from arent import scenarios
from planner.context import BattleContext

STAGE3_CLASSES = ("melee", "fast", "reach", "ranged", "mobile_archer", "tank")


def _side(raw, prefix):
    return [t for t in raw["tokens"] if t["id"].startswith(prefix)]


#--- 1. профили классов покрывают новые роли Этапа 3 ---------------------------
def test_duel_profiles_cover_stage3_classes():
    for cls in STAGE3_CLASSES:
        prof = scenarios.STAGE2_DUEL_PROFILES[cls]
        assert prof["classes"] == [cls]
        assert prof["arsenals"], f"{cls}: пустой арсенал"


#--- 2. матрица пар: каждая unordered-пара дана в ОБОИХ порядках ---------------
def test_stage3_pool_covers_both_orderings():
    pool = scenarios.generate_stage3_pool(4, seed=303)
    # для каждой unordered-пары присутствуют ОБА порядка состава (A-vs-B и B-vs-A)
    ordered = {(p["side_a_classes"][0], p["side_b_classes"][0]) for _n, _r, p in pool}
    for a, b in scenarios.STAGE3_PAIRS:
        assert (a, b) in ordered, f"нет порядка {a}v{b}"
        assert (b, a) in ordered, f"нет порядка {b}v{a} (нарушена симметрия состава §1.9)"


#--- 3. асимметрия по классу: стороны заведомо разных классов ------------------
def test_stage3_pairs_are_class_asymmetric():
    for name, raw, p in scenarios.generate_stage3_pool(3, seed=11):
        assert p["side_a_classes"] != p["side_b_classes"], f"{name}: стороны одного класса"
        assert p["n_allies"] == 1 and p["n_foes"] == 1
        assert p["n_walls"] == 0 and p["layout"] == "structured"
        assert name.startswith("s3_")


#--- 4. бои валидны (hostile targets, src жив, оружие есть) --------------------
def test_stage3_pool_are_valid_fights():
    for name, raw, _p in scenarios.generate_stage3_pool(3, seed=5):
        payload = arena.build_payload(raw, name)
        ctx = BattleContext.from_payload(payload)
        assert ctx.hostile_targets() and ctx.src.is_alive and payload.get("weapons")


#--- 5. имена не пересекаются с пулами Этапа 2 ----------------------------------
def test_stage3_names_disjoint_from_stage2():
    s3 = {n for n, _r, _p in scenarios.generate_stage3_pool(3, seed=9)}
    s2 = set()
    for c in ("melee", "fast", "reach", "ranged"):
        s2 |= {n for n, _r, _p in scenarios.generate_mirror_duels(c, 3, seed=9)}
        s2 |= {n for n, _r, _p in scenarios.generate_asym_duels("ranged", "melee", 3, seed=9)}
    assert s3 and s2
    assert not (s3 & s2), "group_id Этапа 3 пересёкся с Этапом 2"


#--- 6. детерминизм по seed -----------------------------------------------------
def test_stage3_deterministic_for_a_seed():
    a = scenarios.generate_stage3_pool(3, seed=77)
    b = scenarios.generate_stage3_pool(3, seed=77)
    assert [x[0] for x in a] == [x[0] for x in b]
