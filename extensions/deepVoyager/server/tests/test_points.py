# tests/test_points.py — коэффициенты планировщика: встроенные значения, JSON,
# перезагрузка на ходу. Числа влияют и на решения, поэтому проверяем оба слоя:
# сам загрузчик и то, что scoring/service/armament действительно их читают.
from dataclasses import replace
import json

from conftest import make_scene_payload, make_weapon
from planner import points
from planner.action import move_action, target_action, use_action
from planner.armament import DOUBT, SURE, parse_weapons
from planner.context import BattleContext
from planner.scoring import Scorer
from planner.service import PlannerService


def write_points(path, data):
    """Записать points.json (dict -> UTF-8 JSON) и вернуть путь."""
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_defaults_match_previous_constants():
    # числа исторически живут в scoring/armament/geometry — перенос не должен их сдвинуть
    t = points.default_tuning()
    rewards = (t.move_per_cell, t.attack_sure, t.attack_doubt, t.damage_penalty)
    assert rewards == (1.0, 30.0, 15.0, -30.0)
    assert (t.feet_per_cell, t.point_blank_cells, t.reach_tolerance) == (5.0, 1.0, 0.5)
    assert (t.default_melee_ft, t.thrown_property, t.plan_time_limit_sec) == (5.0, "thr", 5.0)


def test_shipped_json_is_valid_and_matches_defaults():
    t, notes = points.read(points.POINTS_FILE)
    assert notes == []                       # поставляемый файл без замечаний
    assert t == points.default_tuning()      # это шаблон, а не «затюненный» конфиг


def test_partial_override_keeps_other_values(tmp_path):
    p = write_points(tmp_path / "points.json", {"actions": {"attack": {"sure": 50}}})
    t, notes = points.read(p)
    assert notes == []
    assert t.attack_sure == 50.0
    assert (t.attack_doubt, t.move_per_cell, t.reach_tolerance) == (15.0, 1.0, 0.5)


def test_point_blank_feet_converts_to_cells(tmp_path):
    # пользователь думает футами: 15 футов помехи при клетке 5 футов = 3 клетки
    p = write_points(tmp_path / "points.json", {"rules": {"pointBlankFt": 15}})
    t, _ = points.read(p)
    assert t.point_blank_cells == 3.0
    # при другом размере клетки то же правило даёт другое число клеток
    p = write_points(tmp_path / "points.json", {"rules": {"pointBlankFt": 15, "feetPerCell": 10}})
    t, _ = points.read(p)
    assert t.point_blank_cells == 1.5


def test_unknown_key_is_reported_not_fatal(tmp_path):
    p = write_points(tmp_path / "points.json",
                     {"actions": {"bogus": 1, "attack": {"sure": 40}}, "чепуха": 2})
    t, notes = points.read(p)
    assert t.attack_sure == 40.0                                  # известное применилось
    assert any("actions.bogus" in n for n in notes)               # опечатка видна в логе
    assert any("чепуха" in n for n in notes)


def test_non_numeric_value_is_reported_and_default_kept(tmp_path):
    p = write_points(tmp_path / "points.json", {"actions": {"attack": {"sure": "много"}}})
    t, notes = points.read(p)
    assert t.attack_sure == 30.0
    assert any("attack.sure" in n for n in notes)


def test_broken_json_falls_back_without_exception(tmp_path):
    p = tmp_path / "points.json"
    p.write_text("{ это не json", encoding="utf-8")
    t, notes = points.read(p)
    assert t == points.default_tuning()
    assert notes and any("разобран" in n or "json" in n.lower() for n in notes)


def test_missing_file_uses_defaults(tmp_path):
    t, notes = points.read(tmp_path / "points.json")
    assert t == points.default_tuning()
    assert any("не найден" in n for n in notes)


def test_tuning_reloads_when_file_changes(tmp_path):
    p = write_points(tmp_path / "points.json", {"actions": {"attack": {"sure": 30}}})
    points.configure(p)
    assert points.tuning().attack_sure == 30.0
    write_points(p, {"actions": {"attack": {"sure": 45}, "move": {"pointsPerCell": 1}}})
    assert points.tuning().attack_sure == 45.0          # без перезапуска сервера


def test_set_tuning_pins_values_over_file(tmp_path):
    p = write_points(tmp_path / "points.json", {"actions": {"attack": {"sure": 45}}})
    points.configure(p)
    previous = points.set_tuning(replace(points.tuning(), attack_sure=99.0))
    assert previous.attack_sure == 45.0                 # вернули прежнее состояние
    write_points(p, {"actions": {"attack": {"sure": 7}}})
    assert points.tuning().attack_sure == 99.0          # пин перекрывает файл


def test_describe_lists_key_coefficients():
    text = points.describe()
    assert "уверенная=30" in text and "сомнительная=15" in text
    assert "вупор=5фт" in text and "клетка=5фт" in text
    assert "лимит=5с" in text


def test_point_blank_threshold_from_config():
    bow = parse_weapons([make_weapon("bow", sure_ft=30, doubt_ft=120, ranged=True)])[0]
    assert bow.mode_at(2.0) == SURE                     # 10 футов — помехи нет
    points.set_tuning(replace(points.default_tuning(), point_blank_cells=3.0))
    assert bow.mode_at(2.0) == DOUBT                    # помеха радиуса 15 футов


def test_scoring_follows_overridden_attack_points():
    points.set_tuning(replace(points.default_tuning(),
                              attack_sure=10.0, attack_doubt=9.0, move_per_cell=2.0))
    ctx = BattleContext.from_payload(make_scene_payload())
    actions = [target_action("B")] + [move_action("right")] * 3 + [use_action("sword")]
    assert Scorer().score(ctx, actions) == 3 * 2.0 + 10.0
    assert "+10" in Scorer().explain(ctx, actions)      # мини-отчёт тоже про новые числа


def test_explain_reports_distance_in_configured_feet():
    points.set_tuning(replace(points.default_tuning(), feet_per_cell=10.0))
    ctx = BattleContext.from_payload(make_scene_payload())
    # 9 клеток по 10 футов: лог в футах, поэтому «90→…», а не «45→…»
    text = Scorer().explain(ctx, [target_action("B")] + [move_action("right")] * 3)
    assert "90→60" in text


def test_service_time_limit_comes_from_tuning():
    points.set_tuning(replace(points.default_tuning(), plan_time_limit_sec=0.0))
    result = PlannerService().run_result(make_scene_payload())
    assert result.considered == 1                       # дедлайн наступил сразу
