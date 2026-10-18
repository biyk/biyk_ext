# tests/test_armament.py — оружие: уверенная/сомнительная дистанции и выбор атаки.
from conftest import make_weapon
from planner.armament import DOUBT, SURE, best_attack, parse_weapons
from planner.points import default_tuning


def test_parse_keeps_fields_and_exposes_cells():
    weapons = parse_weapons([make_weapon("bow", name="лук", sure_ft=30, doubt_ft=120)])
    assert len(weapons) == 1
    bow = weapons[0]
    assert bow.id == "bow" and bow.name == "лук"
    assert bow.damage == "1d6+2" and bow.attack_bonus == 2
    assert bow.sure_ft == 30.0 and bow.doubt_ft == 120.0
    feet = default_tuning().feet_per_cell
    assert (bow.sure_cells, bow.doubt_cells) == (30 / feet, 120 / feet)


def test_parse_skips_junk_and_clamps_doubt():
    weapons = parse_weapons([{"name": "без id"}, {"id": "x", "sureFt": 50, "doubtFt": 20}])
    assert [w.id for w in weapons] == ["x"]
    # сомнительная не может быть короче уверенной
    assert weapons[0].doubt_ft == weapons[0].sure_ft
    # отсутствующие поля — базовые ближний бой/5 футов
    plain = parse_weapons([{"id": "fist"}])[0]
    assert (plain.sure_ft, plain.doubt_ft) == (5.0, 5.0)


def test_melee_zone_is_single_cell_with_diagonal():
    club = parse_weapons([make_weapon("club")])[0]
    assert club.mode_at(0.0) == SURE
    assert club.mode_at(1.41421) == SURE          # диагональный сосед — уверенно
    assert club.mode_at(2.0) is None              # дальше ближний бой не достает


def test_ranged_has_two_zones():
    bow = parse_weapons([make_weapon("bow", sure_ft=30, doubt_ft=120)])[0]
    assert bow.mode_at(6.0) == SURE               # 30 футов = 6 клеток
    assert bow.mode_at(8.0) == DOUBT              # между 30 и 120 футами
    assert bow.mode_at(30.0) is None              # за пределами длинной дистанции


def test_ranged_point_blank_shot_is_downgraded_to_doubt():
    # выстрел в упор (цель в 5 футах) — с помехой, поэтому только сомнительно
    bow = parse_weapons([make_weapon("bow", sure_ft=30, doubt_ft=120, ranged=True)])[0]
    assert bow.mode_at(1.0) == DOUBT              # ортогональный сосед
    assert bow.mode_at(1.41421) == DOUBT          # диагональный сосед — тоже в упор
    assert bow.mode_at(2.0) == SURE               # 10 футов — уже нормально
    melee = parse_weapons([make_weapon("club")])[0]        # ближний бой: дальнобойности нет
    assert melee.ranged is False
    assert melee.mode_at(1.0) == SURE             # вплотную бьёт уверенно


def test_parse_ranged_flag_and_legacy_inference():
    assert parse_weapons([make_weapon("bow", sure_ft=30, doubt_ft=120)])[0].ranged is True
    assert parse_weapons([make_weapon("club")])[0].ranged is False
    # явный ranged=False не перетирается выводом (уродливый лук без длинной дистанции)
    plain = parse_weapons([make_weapon("sling", sure_ft=30, doubt_ft=30, ranged=False)])[0]
    assert plain.ranged is False


def test_parse_properties_and_thrown_flag():
    dagger = parse_weapons([make_weapon("dagger", sure_ft=20, doubt_ft=60,
                                        properties=["thr", "fin"])])[0]
    assert dagger.properties == ("thr", "fin")
    assert dagger.thrown is True
    # метательное не считается дальнобойным: бросок в упор идёт без помехи
    assert dagger.ranged is False
    # мусор в свойствах не должен ломать разбор
    odd = parse_weapons([{"id": "x", "properties": [None, 7, "thr"]}])[0]
    assert odd.properties == ("7", "thr")
    assert parse_weapons([make_weapon("club")])[0].properties == ()


def test_thrown_weapon_is_sure_at_point_blank_and_at_range():
    # метательный нож 20/60 уверенно бьёт и вплотную, и на своей дистанции
    dagger = parse_weapons([make_weapon("dagger", sure_ft=20, doubt_ft=60, ranged=True,
                                       properties=["thr"])])[0]
    assert dagger.mode_at(1.0) == SURE            # ортогональный сосед
    assert dagger.mode_at(1.41421) == SURE        # диагональный сосед
    assert dagger.mode_at(4.0) == SURE            # 20 футов — уверенная зона
    assert dagger.mode_at(8.0) == DOUBT           # 40 футов — длинная дистанция
    assert dagger.mode_at(13.0) is None           # за 60 футами не достать
    # лук (не метательный) на той же дистанции в упор — с помехой
    bow = parse_weapons([make_weapon("bow", sure_ft=30, doubt_ft=120, ranged=True)])[0]
    assert bow.thrown is False
    assert bow.mode_at(1.0) == DOUBT


def test_best_attack_at_point_blank_prefers_sure_thrown_over_ranged():
    # в упор: лук даёт только сомнительную, метательный нож — уверенную
    knife, bow = parse_weapons([make_weapon("knife", sure_ft=20, doubt_ft=60, bonus=1,
                                            ranged=True, properties=["thr"]),
                                make_weapon("bow", sure_ft=30, doubt_ft=120, bonus=5)])
    weapon, mode = best_attack((knife, bow), 1.0)
    assert (weapon.id, mode) == ("knife", SURE)


def test_best_attack_prefers_sure_then_attack_bonus():
    club, bow = parse_weapons([make_weapon("club", bonus=1),
                               make_weapon("bow", sure_ft=30, doubt_ft=120, bonus=5)])
    weapon, mode = best_attack((club, bow), 2.0)
    assert mode == SURE and weapon.id == "bow"    # оба уверенно — берём с большим бонусом
    weapon, mode = best_attack((club, bow), 8.0)
    assert (weapon.id, mode) == ("bow", DOUBT)    # ближний бой не достает
    # в упор дальнобойное с помехой, поэтому выигрывает ближний бой
    weapon, mode = best_attack((club, bow), 1.0)
    assert (weapon.id, mode) == ("club", SURE)


def test_best_attack_none_when_nothing_reaches():
    club = parse_weapons([make_weapon("club")])[0]
    assert best_attack((club,), 2.0) is None
    assert best_attack((), 0.0) is None
