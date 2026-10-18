# planner/armament.py — вооружение NPC: зоны уверенного и сомнительного попадания.
#
# Очки (см. planner/scoring.py): уверенная атака — 30, сомнительная — 15.
#  • ближний бой: зоны совпадают (5 футов, 10 — если у оружия есть досягаемость),
#    поэтому «сомнительного» удара у него не бывает;
#  • дальнобойное: уверенная = range.value (например 30 футов),
#    сомнительная = range.long (например 120 футов);
#  • выстрел в упор (цель в 5 футах) — с помехой, то есть сомнительный;
#  • метательное (свойство thr) — исключение: бросок в упор идёт без помехи,
#    поэтому вплотную и на своей дистанции оно бьёт уверенно.
# Дальности, признаки и свойства приходят из Foundry в поле payload['weapons']
# (см. utils/help.js buildWeapons); старый клиент без новых полей — выводим ranged сам.
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

from planner.geometry import FEET_PER_CELL, REACH_GRID_TOLERANCE

SURE = "sure"       # уверенное попадание
DOUBT = "doubt"     # сомнительное (вне уверенной, но в длинной дистанции)

DEFAULT_MELEE_FT = 5     # базовая дальность ближнего боя в футах
MELEE_THREAT_CELLS = 1.0  # 5 футов — «в упор», для дальнобойного это помеха
THROWN_PROPERTY = "thr"   # свойство dnd5e «метательное»: в упор бьёт без помехи


@dataclass(frozen=True)
class Weapon:
    id: str
    name: str
    damage: str
    attack_bonus: int
    sure_ft: float
    doubt_ft: float
    ranged: bool = False
    properties: Tuple[str, ...] = ()

    @property
    def thrown(self) -> bool:
        """Метательное ли оружие (свойство thr): бросок вплотную — без помехи."""
        return THROWN_PROPERTY in self.properties

    @property
    def sure_cells(self) -> float:
        return self.sure_ft / FEET_PER_CELL

    @property
    def doubt_cells(self) -> float:
        return self.doubt_ft / FEET_PER_CELL

    def mode_at(self, dist_cells: float) -> Optional[str]:
        """Режим попадания на дистанции dist_cells (клетки) — или None, если не достать."""
        # допуск тот же, что у within_reach: полклетки на диагональ/край токена
        if dist_cells <= self.sure_cells + REACH_GRID_TOLERANCE:
            if (self.ranged and not self.thrown
                    and dist_cells <= MELEE_THREAT_CELLS + REACH_GRID_TOLERANCE):
                return DOUBT          # стрелять вплотную — только с помехой
            return SURE
        if dist_cells <= self.doubt_cells + REACH_GRID_TOLERANCE:
            return DOUBT
        return None


def parse_weapons(raw: Optional[Iterable[Dict[str, Any]]]) -> Tuple[Weapon, ...]:
    """Список payload['weapons'] -> кортеж Weapon; записи без id отбрасываются."""
    out = []
    for entry in raw or []:
        wid = entry.get("id")
        if not wid:
            continue
        sure = float(entry.get("sureFt") or DEFAULT_MELEE_FT)
        doubt = float(entry.get("doubtFt") or sure)
        doubt = max(sure, doubt)      # сомнительная не короче уверенной
        props = parse_properties(entry.get("properties"))
        ranged = entry.get("ranged")
        if ranged is None:
            # длинная дистанция бывает только у дальнобойного, но метательное — не он
            ranged = doubt > sure and THROWN_PROPERTY not in props
        out.append(Weapon(
            id=str(wid), name=str(entry.get("name") or wid),
            damage=str(entry.get("damage") or ""), attack_bonus=int(entry.get("attackBonus") or 0),
            sure_ft=sure, doubt_ft=doubt, ranged=bool(ranged), properties=props,
        ))
    return tuple(out)


def parse_properties(raw: Any) -> Tuple[str, ...]:
    """payload['properties'] -> кортеж кодов свойств; мусор (None/числа) — строки без пустых."""
    if isinstance(raw, dict):        # dnd5e 2.x: {"thr": true, ...}
        raw = [k for k, v in raw.items() if v]
    return tuple(str(code) for code in (raw or []) if code not in (None, ""))


def best_attack(weapons: Iterable[Weapon], dist_cells: float) -> Optional[Tuple[Weapon, str]]:
    """(оружие, режим) с максимумом очков атаки на этой дистанции; None — если не достать.

    При равных очках выбирается оружие с большим бонусом атаки.
    """
    best = None
    for weapon in weapons:
        mode = weapon.mode_at(dist_cells)
        if mode is None:
            continue
        key = (1 if mode == SURE else 0, weapon.attack_bonus)
        if best is None or key > best[0]:
            best = (key, weapon, mode)
    return (best[1], best[2]) if best else None
