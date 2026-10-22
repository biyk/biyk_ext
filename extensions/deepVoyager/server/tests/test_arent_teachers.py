# tests/test_arent_teachers.py — реестр учителей не меняет прежнее поведение.
#
# Регрессия по пункту «добавлены регрессионные тесты, подтверждающие неизменность
# прежнего поведения»: greedy-политика через реестр даёт ровно тот же план и значение,
# что прямой Teacher; генерация по умолчанию идентична явной greedy; форма примера
# (JSONL-ключи, размерности, маски, шкала value) не изменилась; выбор по имени и
# неизвестное имя работают как заявлено.
import pytest

from arent import paths, spec
from arent.cli import parser
from arent.dataset import generate
from arent.teacher import Teacher, pinned
from arent.teachers import DEFAULT_TEACHER, TeacherPolicy, get_teacher, list_teachers
from playground.arena import load_arena


def test_registry_offers_greedy_and_it_is_the_default():
    assert DEFAULT_TEACHER == "greedy"
    assert "greedy" in list_teachers()


def test_get_teacher_default_is_a_policy_equal_to_direct_teacher():
    """get_teacher() по умолчанию — это greedy, и метка совпадает с прямой сборкой Teacher."""
    payload = load_arena("corridor_archer")
    with pinned(rounds=1, time_limit_sec=0.5):
        via_registry = get_teacher()
        direct = Teacher(rounds=1, time_limit_sec=0.5)
        assert isinstance(via_registry, TeacherPolicy) and via_registry.name == "greedy"
        a, b = via_registry.label(payload), direct.label(payload)
        assert [x.to_dict() for x in a.actions] == [x.to_dict() for x in b.actions]
        assert (a.value, a.score, a.depth) == (b.value, b.score, b.depth)


def test_greedy_label_is_deterministic():
    payload = load_arena("corridor_archer")
    with pinned(rounds=1, time_limit_sec=0.5):
        first = get_teacher("greedy", rounds=1, time_limit_sec=0.5).label(payload)
        second = get_teacher("greedy", rounds=1, time_limit_sec=0.5).label(payload)
        assert [x.to_dict() for x in first.actions] == [x.to_dict() for x in second.actions]
        assert first.value == second.value and first.score == second.score


def test_unknown_teacher_name_raises_with_hint():
    with pytest.raises(ValueError, match="Неизвестный учитель"):
        get_teacher("no_such_teacher")


def test_generate_default_matches_explicit_greedy_and_records_teacher(tmp_path):
    """Без указания учителя конвейер размечает ровно как с teacher='greedy'."""
    paths.set_workspace(str(tmp_path))
    arenas = ["glass_cannon", "corridor_archer", "fork_two_melee"]
    with pinned(rounds=1, time_limit_sec=0.5):
        default_samples, default_stats = generate(
            count=4, seed=3, per_src=1, rounds_max=0, want_arenas=arenas, use_live=False)
        greedy_samples, _ = generate(
            count=4, seed=3, per_src=1, rounds_max=0, want_arenas=arenas, use_live=False,
            teacher="greedy")
    assert default_stats["teacher"] == "greedy"
    assert default_samples and _shape(default_samples) == _shape(greedy_samples)


def test_sample_shape_and_value_scale_are_unchanged(tmp_path):
    """Формат примера BC не зависит от реестра: те же ключи, длины, маски и шкала value."""
    paths.set_workspace(str(tmp_path))
    with pinned(rounds=1, time_limit_sec=0.5):
        samples, _ = generate(count=2, seed=5, per_src=1, rounds_max=0,
                              want_arenas=["corridor_archer"], use_live=False)
    for s in samples:
        assert set(s) == {"schema", "state", "cells", "targets", "weapons", "mask", "legal",
                          "y", "value", "meta"}
        assert s["schema"] == spec.SCHEMA
        assert len(s["state"]) == spec.dims()["state"]
        assert len(s["mask"]["cells"]) == spec.K_CELLS + 1
        assert len(s["mask"]["targets"]) == spec.K_TARGETS + 1
        assert len(s["mask"]["weapons"]) == spec.K_WEAPONS + 1
        # legal — 3D-маска A(s) размером ровно по длине векторов голов
        assert len(s["legal"]) == spec.K_CELLS + 1
        assert len(s["legal"][0]) == spec.K_TARGETS + 1
        assert len(s["legal"][0][0]) == spec.K_WEAPONS + 1
        assert -3.0 <= s["value"] <= 3.0


def test_cli_gen_defaults_to_greedy_teacher():
    args = parser().parse_args(["gen"])
    assert args.teacher == "greedy"


def _shape(samples):
    """Стабильная форма для сравнения двух прогонов: план, маски и разметка без meta-шума."""
    return [(s["y"], tuple(s["mask"]["cells"]), tuple(s["mask"]["targets"]),
             tuple(s["mask"]["weapons"]), s["meta"]["actions"]) for s in samples]
