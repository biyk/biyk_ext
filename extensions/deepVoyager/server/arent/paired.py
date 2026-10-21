# arent/paired.py — парная статистика сравнения двух политик на ОДНИХ сценах.
#
# Сцены — единица наблюдения: для каждой считаем разность метрик (A - B), затем среднее
# по сценам и 95% bootstrap-интервал этой разности (percentile). Интервал отвечает на
# вопрос «стабильно ли преимущество или оно в пределах шума»: если CI разности не накрывает 0,
# направление сдвига заметно на данном наборе; если накрывает — вывод предварительный.
# Детерминированность: бутстрап на seeded random.Random, повтор запуска даёт тот же CI.
from statistics import mean
from typing import Any, Dict, List, Optional, Sequence, Tuple


def align(rows_a: List[Dict[str, Any]], rows_b: List[Dict[str, Any]],
          key: str = "name") -> Dict[Any, Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Сопоставить строки двух прогонов по ключу сцены; в результат войдут только общие."""
    ia = {r[key]: r for r in rows_a}
    ib = {r[key]: r for r in rows_b}
    common = [k for k in ia if k in ib]
    return {k: (ia[k], ib[k]) for k in common}


def diff_series(paired: Dict[Any, Tuple[Dict[str, Any], Dict[str, Any]]],
                metric: str) -> List[float]:
    """Ряд разностей (A - B) по метрике для всех сопоставленных сцен (пропуск без ключа)."""
    out = []
    for (_a, _b) in paired.values():
        va, vb = paired_get(_a, metric), paired_get(_b, metric)
        if va is not None and vb is not None:
            out.append(float(va) - float(vb))
    return out


def paired_get(row: Dict[str, Any], metric: str) -> Optional[float]:
    """Метрика строки; поддержка производной dmg_net = dealt - taken; None если нет данных."""
    if metric in row and row[metric] is not None:
        return float(row[metric])
    if metric == "dmg_net" and "dmg_dealt" in row and "dmg_taken" in row:
        return float(row["dmg_dealt"]) - float(row["dmg_taken"])
    return None


def bootstrap_ci(values: Sequence[float], resamples: int = 4000, seed: int = 1234,
                 confidence: float = 0.95) -> Dict[str, Any]:
    """Среднее + percentile bootstrap CI по ряду разностей; пустой ряд -> n=0, CI=None."""
    import random
    vals = [float(v) for v in values]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "ci_lo": None, "ci_hi": None, "positive_share": None}
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        sample = [vals[rng.randrange(n)] for _ in range(n)]
        means.append(mean(sample))
    means.sort()
    lo_idx = int((1.0 - confidence) / 2.0 * resamples)
    hi_idx = int((1.0 + confidence) / 2.0 * resamples) - 1
    lo_idx = max(0, min(lo_idx, resamples - 1))
    hi_idx = max(0, min(hi_idx, resamples - 1))
    return {"n": n, "mean": round(mean(vals), 4), "ci_lo": round(means[lo_idx], 4),
            "ci_hi": round(means[hi_idx], 4),
            "positive_share": round(sum(1 for v in vals if v > 0) / n, 3)}


def summarize_paired(rows_a: List[Dict[str, Any]], rows_b: List[Dict[str, Any]],
                     metrics: Sequence[str], key: str = "name",
                     resamples: int = 4000, seed: int = 1234) -> Dict[str, Any]:
    """Сводка A−B по метрикам: пер-сценные разности + среднее + bootstrap CI + доля сцен в плюс A."""
    paired = align(rows_a, rows_b, key)
    per_scenario = {}
    for scene, (a, b) in paired.items():
        per_scenario[scene] = {m: (round(paired_get(a, m) - paired_get(b, m), 4)
                                   if paired_get(a, m) is not None
                                   and paired_get(b, m) is not None else None) for m in metrics}
    stats = {m: bootstrap_ci(diff_series(paired, m), resamples, seed) for m in metrics}
    return {"scenes": len(paired), "a_minus_b": True, "per_scenario_diff": per_scenario,
            "diff_stats": stats}
