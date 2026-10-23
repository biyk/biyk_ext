# tests/test_dagger_aggregate.py — DAgger-агрегация: учитель размечает ПОСЕЩЁННЫЕ политикой состояния.
#
# Суть смены алгоритма (§выбор пользователя): вместо PPO-доводки (которая 4 прогона подряд ломала
# BC) учимся на действиях сильнейшего учителя ровно в тех состояниях, куда сама политика заходит.
# Убирает covariate shift: классический BC размечает только стартовые сцены (dataset.variants),
# а политика, сбившись, попадает в состояния вне обучающего покрытия и ошибки накапливаются.
# Здесь: прогон политики по PolyFightEnv -> на каждом шаге берём живой ctx -> label_ctx -> пример.
# Тест без torch: политику играет учитель-контроллер ("greedy") — ту же среду/тот же .label(...).
from playground import arena
from arent import dagger, scenarios, spec3, team_eval


def _pool(n=2, seed=11):
    return [(name, arena.build_payload(raw, name))
            for name, raw, _p in scenarios.generate_stage3_pool(n, seed)]


def test_aggregate_collects_schema3_samples_from_visited_states():
    policy = team_eval.build_controller("greedy")          # туземный stand-in модели (без torch)
    samples, stats = dagger.aggregate(policy, _pool(), rounds_cap=6, draw_window=4, schema=spec3.SCHEMA)
    assert samples, f"DAgger не собрал ни одного примера: stats={stats}"
    assert all(s["schema"] == spec3.SCHEMA for s in samples)
    assert all(set(s["y"]) == {"plan", "target", "weapon"} for s in samples)
    # каждый пример помечен как собранный учителем на посещённом состоянии
    assert all(s["meta"].get("dagger") is True for s in samples)


def test_aggregate_dedups_states():
    policy = team_eval.build_controller("greedy")
    samples, stats = dagger.aggregate(policy, _pool(), rounds_cap=6, schema=spec3.SCHEMA)
    # уникальность по state_key: агрегат хранит ровно столько примеров, сколько уникальных состояний
    assert stats["kept"] == len(samples)
    assert stats["kept"] <= stats["visited"]                    # дубли отброшены (seen-множество)


def test_aggregate_uses_strongest_teacher_per_role():
    # по замеру battlecast силён во всех ролях -> агрегация размечает его планом (PPO нет).
    policy = team_eval.build_controller("greedy")
    _samples, stats = dagger.aggregate(policy, _pool(), rounds_cap=6, schema=spec3.SCHEMA)
    assert set(stats["teachers"]) <= {"battlecast"}, stats["teachers"]


def test_aggregate_respects_max_samples():
    policy = team_eval.build_controller("greedy")
    samples, _stats = dagger.aggregate(policy, _pool(3, 404), rounds_cap=8, schema=spec3.SCHEMA,
                                       max_samples=5)
    assert len(samples) <= 5
