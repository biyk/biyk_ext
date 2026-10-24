# arent/tactics_config.py — загрузка и живая перезагрузка секции tactics из points.json.
#
# SPEC планировщика (planner/points_spec) знает только плоские числа; tactics — вложенная
# секция с динамическими ключами-тегами, поэтому читается здесь, отдельно, но с тем же
# hot-reload (mtime+размер файла). Ключи weights/penalties валидируются против реестра
# arent/tactics.py: опечатка = ValueError при загрузке, а не молчаливый нулевой вес (§2.3).
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from arent.tactics import ALL_KEYS, BONUS_KEYS, PENALTY_KEYS, decay_linear
from planner import points as _points

_DEFAULT_WEIGHTS: Dict[str, float] = {}
_DEFAULT_PENALTIES: Dict[str, float] = {}


@dataclass(frozen=True)
class DistanceField:
    """Непрерывная дистанционная шкала для дальнобойного (переразметка наград).

    Награда как функция r = дистанция_до_ближней_melee-угрозы / R_conf (R_conf = reach оружия,
    «дистанция уверенной атаки»): штраф при r<near_cut, рост к +amp при r=peak, спад к 0 при
    r=far_cut. enabled=False (по умолчанию) -> поле не влияет на shaping (обратная совместимость).
    """
    enabled: bool = False
    amp: float = 0.15
    near_cut: float = 0.30
    peak: float = 1.0
    far_cut: float = 2.0


@dataclass(frozen=True)
class TacticsConfig:
    """Действующая секция tactics. Пустые weights/penalties = shaping выключен по существу."""
    enabled_global: bool = True
    cap_of_win: float = 0.3
    decay_mode: str = "linear"
    decay_floor: float = 0.0
    weights: Dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_WEIGHTS))
    penalties: Dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_PENALTIES))
    per_stage_disable: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    distance_field: DistanceField = field(default_factory=DistanceField)
    # единое место управления: базовые события исхода (уже сведённые к эффективному числу:
    # enabled=False -> 0.0) и теги, глобально снятые флагом enabled=False (mineus в allowed()).
    base: Dict[str, float] = field(default_factory=dict)
    disabled: frozenset = frozenset()

    def lam(self, iter_index: int, total_iters: int) -> float:
        """λ(iter): decay_mode=linear -> затухание к decay_floor; unknown -> 1.0 (без затухания)."""
        if self.decay_mode == "linear":
            return decay_linear(iter_index, total_iters, self.decay_floor)
        return 1.0

    def allowed(self, stage: Optional[str] = None) -> set:
        """Ключи, разрешённые на этом этапе: реестр минус глобально снятые (enabled=False)
        минус per_stage_disable[stage]."""
        out = (set(self.weights) | set(self.penalties)) - set(self.disabled)
        if stage is not None:
            out -= set(self.per_stage_disable.get(stage, ()))
        return out


def _base_entry(entry: Any) -> Tuple[float, bool]:
    """Запись base -> (число, enabled). Форма: {value, enabled} или голое число (enabled=True)."""
    if isinstance(entry, dict):
        return float(entry.get("value", 0.0)), bool(entry.get("enabled", True))
    return float(entry), True


def _parse_base(section: dict) -> Dict[str, float]:
    """tactics.base -> {имя_события: эффективное число}; enabled=False -> 0.0 (вклад гаснет)."""
    out: Dict[str, float] = {}
    for key, entry in (section.get("base") or {}).items():
        value, enabled = _base_entry(entry)
        out[key] = value if enabled else 0.0
    return out


def _parse_disabled(section: dict) -> frozenset:
    """tactics.tags -> frozenset ключей с enabled=False (опечатка в ключе = ValueError, §2.3)."""
    out = set()
    for key, entry in (section.get("tags") or {}).items():
        if key not in ALL_KEYS:
            raise ValueError(f"tactics.tags: неизвестный ключ {key!r} (реестр arent/tactics)")
        enabled = True if not isinstance(entry, dict) else bool(entry.get("enabled", True))
        if not enabled:
            out.add(key)
    return frozenset(out)


def parse(section: Optional[dict]) -> TacticsConfig:
    """raw['tactics'] -> TacticsConfig с проверкой ключей против реестра. Нет секции -> выкл."""
    if not isinstance(section, dict) or not section:
        return TacticsConfig(enabled_global=False)
    for key in section.get("weights", {}):
        if key not in BONUS_KEYS:
            raise ValueError(f"tactics.weights: неизвестный ключ {key!r} (реестр arent/tactics)")
    for key in section.get("penalties", {}):
        if key not in PENALTY_KEYS:
            raise ValueError(f"tactics.penalties: неизвестный ключ {key!r} (реестр arent/tactics)")
    decay = section.get("decay") or {}
    disable = {str(s): tuple(v) for s, v in (section.get("per_stage_disable") or {}).items()}
    dfr = section.get("distance_field") or {}
    distance_field = DistanceField(
        enabled=bool(dfr.get("enabled", False)),
        amp=float(dfr.get("amp", DistanceField.amp)),
        near_cut=float(dfr.get("near_cut", DistanceField.near_cut)),
        peak=float(dfr.get("peak", DistanceField.peak)),
        far_cut=float(dfr.get("far_cut", DistanceField.far_cut)),
    )
    return TacticsConfig(
        enabled_global=bool(section.get("enabled_global", True)),
        cap_of_win=float(section.get("shaping_cap_of_win", 0.3)),
        decay_mode=str(decay.get("mode", "linear")),
        decay_floor=float(decay.get("floor", 0.0)),
        weights={k: float(v) for k, v in (section.get("weights") or {}).items()},
        penalties={k: float(v) for k, v in (section.get("penalties") or {}).items()},
        per_stage_disable=disable,
        distance_field=distance_field,
        base=_parse_base(section),
        disabled=_parse_disabled(section),
    )


def from_file(path: Optional[str] = None) -> TacticsConfig:
    """Прочитать tactics из points.json (путь: аргумент > POINTS_FILE > server/points.json)."""
    chosen = path or _points.resolve_path()
    try:
        with open(chosen, encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, ValueError):
        return TacticsConfig(enabled_global=False)
    return parse(raw.get("tactics") if isinstance(raw, dict) else None)


_STATE: Dict[str, object] = {"path": None, "stamp": None, "config": None}


def _stamp(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def config(path: Optional[str] = None) -> TacticsConfig:
    """Действующая секция tactics; перечитывает points.json, когда он изменился на диске."""
    chosen = path or _points.resolve_path()
    if path is None and _STATE["config"] is not None and _STATE["path"] == chosen:
        stamp = _stamp(chosen)
        if stamp == _STATE["stamp"]:
            return _STATE["config"]                     # hot-reload: файл не тронут
    fresh = from_file(chosen)
    _STATE.update(path=chosen, stamp=_stamp(chosen), config=fresh)
    return fresh


def set_config(new: Optional[TacticsConfig]) -> None:
    """Зафиксировать конфигурацию (тесты/изоляция от чужого points.json); None — снять."""
    _STATE.update(path=None, stamp=None, config=new)
