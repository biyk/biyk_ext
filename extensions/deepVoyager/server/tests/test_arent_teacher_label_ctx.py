# tests/test_arent_teacher_label_ctx.py — учитель размечает ЖИВОЙ BattleContext, не только payload.
#
# Нужно для DAgger: агрегируем состояния, которые реально посещает текущая политика (они живут
# в среде как ctx), и просим учителя дать эталонный ход ровно в них. refactoring: label(payload)
# = from_payload + label_ctx(ctx); обе функции обязаны давать идентичный Labeled (тот же план,
# value, score, depth), иначе разметка on-policy разъедется с разметкой стартовых сцен.
from arent.battlecast import BattlecastTeacher
from arent.teacher import Teacher
from arent.teachers import get_teacher
from planner.context import BattleContext
from playground.arena import load_arena


def test_greedy_label_ctx_equals_label_payload():
    payload = load_arena("corridor_archer")
    t = Teacher(rounds=1, time_limit_sec=0.5)
    ctx = BattleContext.from_payload(payload)
    via_payload = t.label(payload)
    via_ctx = t.label_ctx(ctx)
    assert [x.to_dict() for x in via_payload.actions] == [x.to_dict() for x in via_ctx.actions]
    assert (via_payload.value, via_payload.score, via_payload.depth) == \
        (via_ctx.value, via_ctx.score, via_ctx.depth)
    assert via_ctx.ctx is ctx                      # размеченный контекст — тот же живой объект


def test_battlecast_label_ctx_equals_label_payload():
    payload = load_arena("corridor_archer")
    t = BattlecastTeacher()
    ctx = BattleContext.from_payload(payload)
    via_payload, via_ctx = t.label(payload), t.label_ctx(ctx)
    assert [x.to_dict() for x in via_payload.actions] == [x.to_dict() for x in via_ctx.actions]
    assert via_payload.value == via_ctx.value
    assert via_ctx.ctx is ctx


def test_registry_teachers_expose_label_ctx():
    # оба учителя реестра обязаны поддерживать ctx-вход (контракт для DAgger-агрегации).
    for name in ("greedy", "battlecast"):
        t = get_teacher(name, rounds=1, time_limit_sec=0.5)
        assert hasattr(t, "label_ctx"), "%s не размечает живой контекст" % name
