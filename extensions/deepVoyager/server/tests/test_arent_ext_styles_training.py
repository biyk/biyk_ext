# tests/test_arent_ext_styles_training.py — Фаза D: новые стили подключаются к ОБУЧЕНИЮ.
#
# Фаза D почти целиком ОПЕРАЦИОННАЯ: инфраструктура уже реестро-управляемая, и задача —
# доказать, что стили Фазы A/C реально служат тремя ролями обучения БЕЗ правок боевого ядра:
#  1) BC-демо-учитель (D1): dataset.generate(teacher=<стиль>, schema=5) выдаёт ненулевую
#     v5-выборку совместимой формы — т.е. мульти-учитель в демо-петле законен.
#  2) PPO-оппонент (D2): team_eval.build_controller(<имя>) -> TeacherController, и стиль
#     доигрывает командный бой (fight_teams) без исключения — значит годится в duel/opponents-микс.
#  3) Переносимость конфига микса (D2): RlConfig сохраняет opponents/duel_opponents-кортеж
#     через to_dict/from_dict — пайплайн может передать микс имён, не трогая ядро.
# Это characterization-тесты контракта: они обязаны быть зелёными УЖЕ (реестр generic), и
# фиксируют его от регресса, когда стили попадут в реальные прогоны.
import pytest

from playground import arena
from arent import dataset, scenarios, spec5
from arent.rollout import RlConfig
from arent.team_eval import TeacherController, build_controller, fight_teams

STYLES = ("battlecast", "battlecast_v2", "ja2_positioning", "ufo_style", "cdda_ranged_support")


def _stage43_pool(n: int = 4, seed: int = 2026):
    out = []
    for name, raw, _params in scenarios.generate_stage43_canon(n, seed=seed):
        out.append((name, arena.build_payload(raw, name)))
    return out


# ───────────────────────────────── D1: стиль = валидный v5 BC-демо-учитель
@pytest.mark.parametrize("style", STYLES)
def test_style_is_a_valid_v5_bc_demo_teacher(style):
    pool = _stage43_pool()
    samples, stats = dataset.generate(
        count=12, seed=7, per_src=4, rounds_max=4, teacher=style, teacher_limit=None,
        scenario_pool=pool, include_arenas=False, use_live=False, schema=spec5.SCHEMA)
    assert samples, f"{style}: v5-демо пусто (skip={stats['skip']})"
    assert stats["teacher"] == style
    for s in samples:
        assert s["schema"] == spec5.SCHEMA
        dataset.assert_compatible(s)              # форма/версия признаков совместны


# ───────────────────────────────── D2: стиль = валидный PPO-оппонент (контроллер + бой)
@pytest.mark.parametrize("style", STYLES)
def test_style_resolves_to_teacher_controller(style):
    ctrl = build_controller(style, schema=spec5.SCHEMA)
    assert isinstance(ctrl, TeacherController)
    assert ctrl.describe().startswith(style + "@")   # имя попало в описание оппонента


@pytest.mark.parametrize("style", STYLES)
def test_style_finishes_a_team_battle_as_opponent(style):
    name, payload = _stage43_pool(1)[0]
    row = fight_teams(payload, candidate="battlecast", opponent=style,
                      schema=spec5.SCHEMA, rounds_cap=4)
    assert row["outcome"] in ("win", "loss", "draw", "open", "mutual")
    assert row["opponent_steps"] > 0                # стиль реально ходил своей командой


# ───────────────────────────────── D2: конфиг микса переносится (round-robin-лист имён)
def test_rlconfig_carries_opponent_mix_roundtrip():
    mix = ("battlecast", "ufo_style", "cdda_ranged_support", "ja2_positioning")
    cfg = RlConfig(opponents=mix, duel_opponents=mix)
    back = RlConfig.from_dict(cfg.to_dict())
    assert tuple(back.opponents) == mix
    assert tuple(back.duel_opponents) == mix
