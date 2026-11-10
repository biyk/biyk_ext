# arent/curriculum.py — D4: расписание силы оппонентов (weak -> strong), БЕЗ torch.
#
# Почему отдельный модуль. Разбор env-строки куррикулума делает ДРАЙВЕР прогона
# (.ray/ray_stage5_pipeline.py -> _parse_curriculum_env), а драйвер Ray Client на Windows
# живёт в .ray/.venv БЕЗ torch: torch есть только в GPU-worker'ах на head. Импорт
# arent.rollout тянет arent.torch_rl -> ImportError ещё до старта прогона. Поэтому чистые
# данные расписания лежат здесь (только stdlib), а arent.rollout реэкспортирует их для
# всех внутренних потребителей (rl.py, тесты) — источник правды один.
#
# Формат (env S5_PPO_CURRICULUM): 'start:opp1,opp2;start2:opp...'.
# Стадии сортируются по start_iter; на итерации it активна последняя стадия с start<=it.
from typing import Any, List, Tuple

Stages = Tuple[Tuple[int, Tuple[str, ...]], ...]


def parse_curriculum(spec: str) -> Stages:
    """Разобрать env-строку куррикулума 'start:opp1,opp2;start2:opp...' в стадии.

    Пустая строка -> () (куррикулума нет). Стадии сортируются по start_iter. Кривой
    start (не int) -> ValueError: молча игнорировать расписание опаснее, чем упасть."""
    stages: List[Tuple[int, Tuple[str, ...]]] = []
    for chunk in (spec or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        start_s, sep, opp_s = chunk.partition(":")
        if not sep:
            raise ValueError("куррикулум: стадия %r без ':' (нужно 'start:opp1,opp2')" % chunk)
        try:
            start = int(start_s.strip())
        except ValueError as exc:
            raise ValueError("куррикулум: start=%r не целое (стадия %r)" % (start_s.strip(), chunk)) from exc
        opps = tuple(x.strip() for x in opp_s.split(",") if x.strip())
        if not opps:
            raise ValueError("куррикулум: стадия %r без оппонентов" % chunk)
        stages.append((start, opps))
    stages.sort(key=lambda s: s[0])
    return tuple(stages)


def curriculum_opponents(cfg: Any, iteration: int) -> Tuple[str, ...]:
    """Активный набор оппонентов на итерации PPO по куррикулуму (D4).

    cfg — любой объект с полями opponents/curriculum (RlConfig), поэтому импорт RlConfig
    сюда НЕ нужен: модуль остаётся torch-free и годится драйверу. Пустой curriculum ->
    cfg.opponents (прежнее поведение). До первой стадии — cfg.opponents как безопасный
    фолбэк (пустой список уронил бы collect_asymmetric). Вход не мутируется."""
    if not cfg.curriculum:
        return tuple(cfg.opponents)
    active: Tuple[str, ...] = tuple(cfg.opponents)
    for start, stage in cfg.curriculum:
        if iteration >= int(start):
            active = tuple(stage)
        else:
            break
    return active
