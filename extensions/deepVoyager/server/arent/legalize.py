# arent/legalize.py — единый механизм совместной легальности и исправления действия.
#
# Головы сети маскируются НЕЗАВИСИМО (куда / в кого / чем), но атака легальна УСЛОВНО:
# выбранное оружие должно доставать выбранную цель ИЗ ПОЗИЦИИ АТАКИ выбранной клетки/плана
# и по линии видимости. Единственная правда об этой совместной проверке живёт в двух
# примитивах: slots.attackable (схема 2) и slots_v3.attackable_v3 (схема 3). Этот модуль
# оборачивает их в один компонент с явным интерфейсом, чтобы СРЕДА ОБУЧЕНИЯ и ПУТИ ИНФЕРЕНСА
# (play, evaluate, team_eval) применяли ровно одно и то же правило и одинаково его чинили.
#
# Семантика исправления сохранена без новой боевой логики: невозможную атаку убираем до
# «не атаковать» (NONE), движение и прицел остаются законным ходом — ровно так, как это
# делал FightEnv.legalize/PolyFightEnv.legalize. Проверка ЧИСТАЯ: она читает ctx/slots,
# ничего не двигает и не ранит (можно вызывать ради диагностики без побочного эффекта).
from typing import Any, Dict, Optional, Tuple

from arent import slots as slots_mod, slots_v3, spec, spec3

NONE_INDEX = spec.K_WEAPONS            # «не атаковать» = последний слот оружия (совпадает с env.NONE_INDEX)

REASON_UNREACHABLE = "attack_unreachable_or_no_los"   # цель не достать/нет LOS из позиции атаки


def is_legal(action: Dict[str, int], schema: int, slots: Any, ctx: Any) -> bool:
    """True, если тройка уже совместна (это «не атака» или законная атака). Только чтение боя."""
    if schema == spec3.SCHEMA:
        pos, key = int(action.get("plan", 0)), "plan"
    else:
        pos, key = int(action.get("cell", 0)), "cell"
    target = int(action.get("target", spec.NONE_SLOT))
    weapon = int(action.get("weapon", spec.NONE_SLOT))
    if not (0 <= target < len(slots.targets) and 0 <= weapon < len(slots.weapons)):
        return True                                        # «не стрелять/не атаковать» — всегда законно
    if schema == spec3.SCHEMA:
        return slots_v3.attackable_v3(slots, ctx, pos, target, weapon)
    return slots_mod.attackable(slots, ctx, pos, target, weapon)


def legalize(action: Dict[str, int], schema: int, slots: Any,
             ctx: Any) -> Tuple[Dict[str, int], Optional[str]]:
    """Совместная легальность (cell|plan, target, weapon) -> (исправленное, причина|None).

    Ключ позиции выбирается по схеме ("cell"/"plan"), что сохраняет контракт decode каждой
    схемы. Причина — None, когда предложение уже законно (идемпотентно), иначе код правки.
    """
    key = "plan" if schema == spec3.SCHEMA else "cell"
    pos = int(action.get(key, 0))
    target = int(action.get("target", spec.NONE_SLOT))
    weapon = int(action.get("weapon", spec.NONE_SLOT))
    out = {key: pos, "target": target, "weapon": weapon}
    if 0 <= target < len(slots.targets) and 0 <= weapon < len(slots.weapons):
        if schema == spec3.SCHEMA:
            reachable = slots_v3.attackable_v3(slots, ctx, pos, target, weapon)
        else:
            reachable = slots_mod.attackable(slots, ctx, pos, target, weapon)
        if not reachable:
            out["weapon"] = NONE_INDEX                     # атака невозможна -> только движение/прицел
            return out, REASON_UNREACHABLE
    return out, None
