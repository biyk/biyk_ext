# arent/tactics_map.py — карта «архетип/арена -> ожидаемые тактики» (§3).
#
# Нужна arena-гейту (§1.4): бонус тактики начисляется только там, где тактика применима по
# смыслу арены. Для генерируемых арен expected выводим из params (archetype + состав + стены)
# функцией infer_strategies, чтобы не переписывать руками. Для замороженных ho_* имя тега
# проставляется явно в манифесте арены и читается через expected_keys(declared=...).
import json
import os
from typing import Any, Dict, List

from arent.tactics import ALL_KEYS

_MAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tactics_map.json")


def _load_map() -> Dict[str, Dict[str, List[str]]]:
    with open(_MAP_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


ARCH_MAP: Dict[str, Dict[str, List[str]]] = _load_map()

RANGED_CLASSES = frozenset({"ranged", "mobile_archer"})
MELEE_CLASSES = frozenset({"melee", "fast", "tank", "reach"})


def entry(archetype: str) -> Dict[str, List[str]]:
    """Базовая карта архетипа; неизвестный архетип -> пусто (ничего не ждём)."""
    return ARCH_MAP.get(archetype, {"enabled": [], "penalties": []})


def infer_strategies(params: Dict[str, Any]) -> Dict[str, List[str]]:
    """{enabled, penalties} из params сценария: архетип + состав сторон + стены + размеры."""
    base = entry(params.get("archetype", ""))
    enabled, penalties = set(base["enabled"]), set(base["penalties"])

    ours = set(params.get("side_a_classes", []))
    foes = set(params.get("side_b_classes", []))
    # свои дальнобойники против чужих милишников -> важно кайтить, нельзя подходить
    if (RANGED_CLASSES & ours) and (MELEE_CLASSES & foes):
        enabled.add("kite_max_range")
        penalties.add("approach_milishnik_as_archer")
    # враг с досягаемостью (reach=10ft) -> не входить в его зону
    if "reach" in foes:
        enabled.add("avoid_reach")
        penalties.update({"enter_reach", "reach_penalty"})
    # на поле есть стены -> стрельба из-за укрытия имеет смысл
    if int(params.get("n_walls", 0)) > 0:
        enabled.add("cover_shoot")
        penalties.add("shoot_from_open")
    # нас минимум двое -> фокус огня против россыпи
    if int(params.get("n_allies", 1)) >= 2:
        enabled.add("focus_fire")
        penalties.add("spread_fire")
    return {"enabled": sorted(enabled), "penalties": sorted(penalties)}


def expected_keys(params: Dict[str, Any], declared: Dict[str, Any] | None = None
                  ) -> Dict[str, List[str]]:
    """Ожидаемые тактики арены: явный манифест (ho_*) важнее вывода из params."""
    if declared and ("enabled" in declared or "penalties" in declared):
        return {"enabled": list(declared.get("enabled", [])),
                "penalties": list(declared.get("penalties", []))}
    return infer_strategies(params)


def allowed_set(expected: Dict[str, List[str]]) -> set:
    """Множество ключей для arena-gate bonus_for; ключи вне реестра отбрасываются (защита)."""
    keys = set(expected.get("enabled", [])) | set(expected.get("penalties", []))
    return {k for k in keys if k in ALL_KEYS}
