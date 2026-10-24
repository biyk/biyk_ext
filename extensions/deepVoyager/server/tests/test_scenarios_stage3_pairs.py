# tests/test_scenarios_stage3_pairs.py — Этап 3: неравные дуэли 1v1 (полный перебор классов).
#
# teaching_plan §Этап 3: модель обязана играть ОТ КЛАССА против ЛЮБОГО врага. Поэтому
# STAGE3_PAIRS — ПОЛНЫЙ перебор «каждый с каждым» (product 6×6 = 36 упорядоченных пар, ВКЛ.
# одноклассовые melee×melee и обе ориентации крест-накрест), а учебная геометрия — открытое
# поле РАЗНОГО размера со СЛУЧАЙНОЙ расстановкой (random_start), чтобы бойцы не привыкали к карте.
# §1.9 (симметрия условий): для каждой пары (a,b) присутствуют обе ориентации (a,b) и (b,a) —
# тогда у каждого класса равное число боёв на A- и на B-зоне. Имена s3_* не коллидируют с s2_*.
# Cross-классовые пары асимметричны по классу; self-пары — один класс, но оружие/статы разные.
import itertools

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


#--- 3. geometry/naming invariants (self-пары теперь разрешены) -----------------
def test_stage3_pairs_are_valid_duels():
    for name, raw, p in scenarios.generate_stage3_pool(3, seed=11):
        a, b = p["side_a_classes"][0], p["side_b_classes"][0]
        assert a in STAGE3_CLASSES and b in STAGE3_CLASSES, f"{name}: чужой класс"
        assert p["n_allies"] == 1 and p["n_foes"] == 1
        assert p["n_walls"] == 0 and p["layout"] == "random"   # Этап 3: открытое поле + random_start
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


#--- 7. полный перебор «каждый с каждым»: все 36 упорядоченных пар, есть self ---
def test_stage3_pool_covers_all_class_pairs():
    pool = scenarios.generate_stage3_pool(2, seed=404)
    ordered = {(p["side_a_classes"][0], p["side_b_classes"][0]) for _n, _r, p in pool}
    want = set(itertools.product(STAGE3_CLASSES, STAGE3_CLASSES))
    assert len(scenarios.STAGE3_PAIRS) == len(want) == 36
    assert ordered == want, f"не покрыты пары: {sorted(want - ordered)}"
    # self-пары (a×a) присутствуют: melee против melee и т.п.
    assert all((c, c) in ordered for c in STAGE3_CLASSES), "нет одноклассовых боёв"


#--- 8. разнообразие геометрии: разные размеры поля и uniform-разброс старта ---
def test_stage3_pool_varies_field_and_placement():
    from arent import scenario_layout as sl
    pool = scenarios.generate_stage3_pool(3, seed=404)
    assert all(p["n_walls"] == 0 for _n, _r, p in pool)          # только открытые поля
    assert all(p["layout"] == "random" for _n, _r, p in pool)    # случайная расстановка
    assert all(p["deployment"] == "uniform" for _n, _r, p in pool)   # random_start -> uniform
    # старты реально разбросаны по полю, а не прикованы к рамке: ряды A гуляют по глубине
    a_rows = [t["cell"][0] for _n, raw, _p in pool for t in raw["tokens"] if t["disposition"] == -1]
    assert max(a_rows) - min(a_rows) > 4, "A-юниты всё ещё на одной рамке"
    # между командами держится минимальная дистанция (бой не стартует впритык)
    for _n, raw, _p in pool:
        ours = [t["cell"] for t in raw["tokens"] if t["disposition"] == -1]
        foes = [t["cell"] for t in raw["tokens"] if t["disposition"] == 1]
        assert all(max(abs(o[0] - f[0]), abs(o[1] - f[1])) >= sl.DEPLOY_MIN_DIST
                   for o in ours for f in foes), "команды стартовали слишком близко"
    # размеры поля НЕ зафиксированы одним (как pin small в Этап 2): заведомо разнородно между seed'ами.
    sizes = set()
    for sd in (404, 900, 11):
        sizes |= {p["field_profile"] for _n, _r, p in scenarios.generate_stage3_pool(1, sd)}
    assert sizes <= {"small", "medium", "large"} and len(sizes) > 1
