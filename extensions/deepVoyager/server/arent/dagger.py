# arent/dagger.py — DAgger-агрегация: учитель размечает ПОСЕЩЁННЫЕ политикой состояния.
#
# Смена алгоритма (§выбор пользователя: «учимся на действиях учителя, пока не сравняемся»):
# вместо PPO-доводки (4 прогона подряд ломала BC) берём текущую политику, гоняем её по
# PolyFightEnv и в КАЖДОМ состоянии, куда она реально зашла, просим сильнейшего в роли
# учителя разметить ход (label_ctx). Так обучающее покрытие следует за политикой и исчезает
# covariate shift: классический BC размечал только стартовые сцены (dataset.variants), а
# политика, сбившись, попадала в состояния вне покрытия и ошибки накапливались.
#
# Ядро переиспользует тот же путь, что и офлайн-BC: dataset.sample_from_labeled_v3 принимает
# готовый Labeled (уже и из живого ctx) и выдаёт пример схемы 3, бит-в-бит совместимый с
# train.run(samples=...). Поэтому DAgger-примеры подмешиваются в датасет напрямую, а агрегат
# дедуплицирует состояния по dataset.state_key (разметка живым учителем — самое дорогое место).
from typing import Any, Dict, List, Optional, Tuple

from arent import dataset, polyenv, spec3, teacher_select, teachers
from arent.team_reward import TeamReward

Row = Dict[str, Any]


def _coerce_schema(policy: Any, schema: int) -> None:
    """Гоним политику в той же схеме, что и среда: контроллеры читают .schema при label()."""
    if hasattr(policy, "schema"):
        policy.schema = int(schema)


def aggregate(policy: Any, sources: List[Tuple[str, Dict[str, Any]]],
              rounds_cap: int = 8, draw_window: int = 4, schema: int = spec3.SCHEMA,
              max_samples: Optional[int] = None,
              role_table: Optional[Dict[str, str]] = None
              ) -> Tuple[List[Row], Row]:
    """Прогнать политику по сценам и собрать (посещённое состояние -> план учителя) примеры BC.

    policy — контроллер с .label(obs, ctx, slots) (team_eval.build_controller от имени учителя,
    весов или готового контроллера): он играет ВСЕХ актёров, поэтому собираем именно те состояния,
    куда политика сама заходит. На каждом шаге роль актёра (teacher_select.derive_role по reach/hp)
    -> сильнейший в роли учитель -> label_ctx(живой ctx) -> sample_from_labeled_v3.

    max_samples — потолок собранных примеров (ранний выход). role_table — переопределить
    «роль -> учитель» (по умолчанию DEFAULT_ROLE_TEACHER: battlecast во всех ролях по замеру).

    stats: visited (сколько посещённых состояний разметили), kept (сколько уникальных примеров
    вошло), teachers (какие учителя реально размечали), skip (почему часть состояний не стала
    примером: no_attack/no_slots/label_out_of_slots/roundtrip_mismatch — диагностика покрытия).
    """
    _coerce_schema(policy, schema)
    env = polyenv.PolyFightEnv(rounds_cap=rounds_cap,
                               team=TeamReward(draw_window=draw_window), schema=schema)
    policy_teachers: Dict[str, Any] = {}          # имя -> экземпляр учителя (кешируем на прогон)

    def labeler(name: str):
        if name not in policy_teachers:
            policy_teachers[name] = teachers.get_teacher(name, rounds=1, time_limit_sec=None)
        return policy_teachers[name]

    samples: List[Row] = []
    seen: set = set()
    stats: Row = {"visited": 0, "kept": 0, "teachers": [], "skip": {},
                  "schema": int(schema), "rounds_cap": rounds_cap, "draw_window": draw_window,
                  "sources": len(sources)}
    used_teachers: set = set()

    for source_name, payload in sources:
        if max_samples is not None and len(samples) >= max_samples:
            break
        obs = env.reset(payload, start_index=0)
        while obs is not None:
            ctx, actor = env._ctx, env.actor
            unit = env.state.units[actor]
            initiative = env.state.initiative_order
            role = teacher_select.derive_role(unit.reach_cells, unit.hp)
            tname = teacher_select.teacher_for_role(role, role_table)
            used_teachers.add(tname)
            stats["visited"] += 1
            labeled = labeler(tname).label_ctx(ctx)
            sample, reason = dataset.sample_from_labeled_v3(
                source_name, labeled, {"dagger": True}, initiative)
            if sample is None:
                stats["skip"][reason] = stats["skip"].get(reason, 0) + 1
            else:
                key = dataset.state_key(sample)
                if key not in seen:
                    seen.add(key)
                    samples.append(sample)
                    stats["kept"] += 1
                    if max_samples is not None and len(samples) >= max_samples:
                        break
            chosen = policy.label(obs, ctx, env.slots)
            obs, _r, terminated, truncated, _info = env.step(chosen)
            if terminated or truncated:
                break
        if max_samples is not None and len(samples) >= max_samples:
            break
    stats["teachers"] = sorted(used_teachers)
    return samples, stats
