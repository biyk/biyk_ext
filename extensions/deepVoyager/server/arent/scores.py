# arent/scores.py — метрики качества политика и разбивка по состояниям.
#
# Вынесено из train.py, чтобы сам цикл обучения остался компактным. Тесты и отчёты
# ссылаются на них как на train.metrics / train.by_source (re-export в train.py).
from typing import Any, Dict, List

from arent.net import GROUPS, Y_KEY, y_index


def metrics(model: Any, samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Доля угаданных слотов по головам + совместная + MAE стоимости."""
    hits = {"cell": 0, "target": 0, "weapon": 0, "joint": 0}
    error = 0.0
    for sample in samples:
        out = model.predict(sample)
        good = []
        for group in GROUPS:
            key = Y_KEY[group]
            same = out[key] == y_index(sample, group)
            good.append(same)
            hits[key] += 1 if same else 0
        hits["joint"] += 1 if all(good) else 0      # все три головы сразу = повторенный план
        error += abs(out["value"] - float(sample.get("value", 0.0)))
    n = max(1, len(samples))
    return {"cell": round(hits["cell"] / n, 3), "target": round(hits["target"] / n, 3),
            "weapon": round(hits["weapon"] / n, 3), "joint": round(hits["joint"] / n, 3),
            "value_mae": round(error / n, 4), "n": len(samples)}


def batches(order: List[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
    return [order[i:i + max(1, size)] for i in range(0, len(order), max(1, size))]


def by_source(model: Any, samples: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Метрики по имени состояния (meta.arena, иначе meta.src): проверка на забывание.

    После дообучения на новых сценах сравнивают эти строчки между прогонами: если joint
    старой арены упал, новые примеры затёрли прежний навык, и датасет надо мешать.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for sample in samples:
        meta = sample.get("meta") or {}
        name = str(meta.get("arena") or meta.get("src") or "?")
        groups.setdefault(name, []).append(sample)
    return {name: metrics(model, chunk) for name, chunk in sorted(groups.items())}
