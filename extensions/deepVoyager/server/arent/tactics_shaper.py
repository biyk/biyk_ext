# arent/tactics_shaper.py — тактический shaping-член: λ-decay, cap за бой, arena-gate, счётчики.
#
# Отдельный (аддитивный) член к награде сверх потенциала Ng'99 (env.shape_reward его уже делает
# для phi). Три правила teaching_plan собраны здесь:
#   • train-only (§1.1): в eval record_only=True — детекторы и счётчики идут, в награду не течёт;
#   • cap (§1.2): |Σ λ·bonus| за бой ≤ cap_of_win·|WIN|, симметрично, счётчик S в shaper, reset чистит;
#   • decay (§1.3): λ(iter)=cfg.lam(iter,total), на концах обучения shaping≈0;
#   • arena-gate (§1.4): bonus_for начисляет только ключи из allowed (expected_strategies арены).
from __future__ import annotations

from typing import Dict, Optional

from arent.tactics import FocusFireAccumulator
from arent.tactics_config import TacticsConfig
from arent.tactics_counters import Counters
from arent.tactics_detect import bonus_for, detect
from arent.team_reward import WIN


class TacticsShaper:
    """Один shaper на среду/бой: держит λ-позицию, кумулятивный shaping S и счётчики трасса."""

    def __init__(self, cfg: TacticsConfig, allowed: set, counters: Optional[Counters] = None,
                 record_only: bool = False) -> None:
        self.cfg = cfg
        self.allowed = set(allowed)
        self.counters = counters if counters is not None else Counters()
        self.record_only = record_only
        self.iter = 0
        self.total = 1
        self.cap_total = cfg.cap_of_win * abs(WIN)
        self.S = 0.0
        self.hp_max: Dict[str, float] = {}
        self.ff = FocusFireAccumulator()

    def reset(self, units: Dict) -> None:
        """Новый бой: shaping-сумма и фокус-аккумулятор с нуля; hp_max засечён по старту."""
        self.S = 0.0
        self.ff = FocusFireAccumulator()
        self.observe_hp(units)

    def observe_hp(self, units: Dict) -> None:
        for uid, u in units.items():
            if u.is_alive:
                self.hp_max[uid] = max(self.hp_max.get(uid, 0.0), float(u.hp))

    def anneal(self, iter_index: int, total_iters: int) -> None:
        self.iter = int(iter_index)
        self.total = max(1, int(total_iters))

    def _cap(self, raw: float) -> float:
        """Обрезка до |S| ≤ cap_total с сохранением направления (к нулю всегда пускаем)."""
        if raw == 0.0:
            return 0.0
        if abs(self.S + raw) <= self.cap_total:
            self.S += raw
            return round(raw, 6)
        bound = self.cap_total if raw > 0 else -self.cap_total
        step = bound - self.S
        self.S = bound
        return round(step, 6)

    def addend(self, ctx) -> float:
        """Шаг shaping: детект -> счётчики -> λ·bonus по allowed -> cap. record_only даёт 0."""
        detection = detect(ctx)
        self.counters.record(detection.applicable, detection.fired, detection.violated)
        if self.record_only:
            return 0.0
        bonus = bonus_for(detection, self.allowed, self.cfg.weights, self.cfg.penalties)
        return self._cap(self.cfg.lam(self.iter, self.total) * bonus)
