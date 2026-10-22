# arent/tactics_counters.py — агрегат трасса по тактикам: follow_rate/correctness (§11.3).
#
# Считается по ВСЕМ применимым шагам трасса, а не по срезу diag[:64]: редкий тег с 3
# наблюдениями не должен давать «60%». На каждый ключ копим applicable/fired/violated/missed.
# follow_rate=fired/applicable (None при small support), correctness для положительного тега =
# fired/applicable же (применимость и правомерность совпадают у детектора, правомерный ход —
# это и есть fired), для отрицательного — «штраф поймал реальный вред». min_support порождает
# N/A вместо ложных 0% (§11.3).
from __future__ import annotations

import math
from typing import Dict

from arent.tactics import KIND

MIN_SUPPORT = 5               # ниже — follow_rate = None (N/A), не 0%


def wilson_interval(successes: int, total: int, z: float = 1.96):
    """Wilson 95% CI для доли; (None, None) при total==0."""
    if total <= 0:
        return (None, None)
    phat = successes / total
    z2 = z * z
    denom = 1 + z2 / total
    center = (phat + z2 / (2 * total)) / denom
    margin = z * math.sqrt(phat * (1 - phat) / total + z2 / (4 * total * total)) / denom
    return (round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4))


class Counters:
    """Кумулятивные счётчики тактик по трассу (applicable/fired/violated на каждый ключ)."""

    def __init__(self) -> None:
        self._app: Dict[str, int] = {}
        self._fired: Dict[str, int] = {}
        self._viol: Dict[str, int] = {}
        self.steps = 0
        self._gate = True             # False -> record() no-op (matchup: считаем лишь кандидата)

    def gate(self, allow: bool) -> None:
        """Включать/выключать агрегацию шагов (§8-I: follow_rate мерит КАНДИДАТА).

        matchup-контур выставляет gate(is_candidate) перед каждым env.step: счётчики видят
        ground-truth трасса целиком (детекторы/фокус-аккумулятор считаются на обоих фронтах),
        но в статистику попадают только шаги кандидата — пустые ходы соперника его не заражают."""
        self._gate = bool(allow)

    def record(self, applicable, fired, violated) -> None:
        if not self._gate:
            return
        self.steps += 1
        for key in applicable:
            self._app[key] = self._app.get(key, 0) + 1
        for key in fired:
            self._fired[key] = self._fired.get(key, 0) + 1
        for key in violated:
            self._viol[key] = self._viol.get(key, 0) + 1

    def follow_rate(self, key: str):
        app = self._app.get(key, 0)
        if app < MIN_SUPPORT:
            return None                          # N/A, а не 0% (§11.3)
        return round(self._fired.get(key, 0) / app, 4)

    def to_dict(self) -> Dict[str, Dict[str, object]]:
        out: Dict[str, Dict[str, object]] = {}
        for key in set(self._app) | set(self._fired) | set(self._viol):
            app = self._app.get(key, 0)
            fired = self._fired.get(key, 0)
            viol = self._viol.get(key, 0)
            numerator = viol if KIND.get(key) == "penalty" else fired
            lo, hi = wilson_interval(numerator, app)
            out[key] = {
                "kind": KIND.get(key, "bonus"),
                "applicable": app, "fired": fired, "violated": viol,
                "missed": max(0, app - fired - viol),
                "follow_rate": self.follow_rate(key),
                "ci_low": lo, "ci_high": hi,
                "gated_zero": app == 0,          # дефект гейта/арены, не провал модели (§11.3)
            }
        return {"steps": self.steps, "min_support": MIN_SUPPORT, "tactics": out}
