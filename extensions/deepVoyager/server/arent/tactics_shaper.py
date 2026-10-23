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
from arent.tactics_detect import bonus_for, detect, distance_field_value
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
        #: as-if-разбор последнего шага для диагностики в трейсе (fired/violated + веса + as-if).
        self.last_diag: Optional[dict] = None

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
        """Шаг shaping: детект -> счётчики -> as-if-разбор -> λ·bonus по allowed -> cap.

        record_only возвращает 0.0 в награду (§1.1), НО as-if-разбор (self.last_diag) пишет всегда:
        именно он нужен, чтобы в трейсе увидеть, какое действие сколько shaping ПОЛУЧИЛО БЫ на
        train — и поймать reward-hacking, когда вредный ход даёт положительный член.
        """
        detection = detect(ctx)
        self.counters.record(detection.applicable, detection.fired, detection.violated)
        allow = set(self.allowed)
        weights = {**self.cfg.weights, **self.cfg.penalties}
        fired = sorted(detection.fired & allow)
        violated = sorted(detection.violated & allow)
        contrib = {k: float(weights.get(k, 0.0)) for k in fired + violated}
        lam = self.cfg.lam(self.iter, self.total)
        bonus = bonus_for(detection, self.allowed, self.cfg.weights, self.cfg.penalties)
        # непрерывная дистанционная шкала дальнобойного (переразметка): не тег, а форма награды
        # по r=дистанция/R_conf; подмешивается в total до cap. enabled=False -> 0 (без изменений).
        field = distance_field_value(ctx, self.cfg.distance_field)
        self.last_diag = {"fired": fired, "violated": violated, "weights": contrib,
                          "field": round(field, 6), "asif": round(lam * (bonus + field), 6)}
        if self.record_only:
            return 0.0
        return self._cap(lam * (bonus + field))
