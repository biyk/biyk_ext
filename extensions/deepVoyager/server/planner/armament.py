# planner/armament.py — вооружение NPC: зоны уверенного и сомнительного попадания.
#
# Очки (см. planner/scoring.py и points.json): уверенная атака — attack.sure (30),
# сомнительная — attack.doubt (15).
#  • ближний бой: зоны совпадают (5 футов, 10 — если у оружия есть досягаемость),
#    поэтому «сомнительного» удара у него не бывает;
#  • дальнобойное: уверенная = range.value (например 30 футов),
#    сомнительная = range.long (например 120 футов);
#  • выстрел в упор (цель в 5 футах) — с помехой, то есть сомнительный;
#  • метательное (свойство thr) — исключение: бросок в упор идёт без помехи,
#    поэтому вплотную и на своей дистанции оно бьёт уверенно.
# Дальности, признаки и свойства приходят из Foundry в поле payload['weapons']
# (см. utils/help.js buildWeapons); старый клиент без новых полей — выводим ranged сам.
# Пороги (5 футов «в упор», допуск reach, базовая ближняя дальность, код свойства
# «метательное») — в points.json, читаются через planner/points.py.
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

from planner.dice import average
from planner.points import tuning

SURE = "sure"       # уверенное попадание
DOUBT = "doubt"     # сомнительное (вне уверенной, но в длинной дистанции)


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
        """Метательное ли оружие (свойство thr из points.json): бросок вплотную без помехи."""
        return tuning().thrown_property in self.properties

    @property
    def expected_damage(self) -> float:
        """Сколько урона ждать от оружия (пункт 5): симуляция меряет ожиданием, а не броском.

        Неразбираемая строка урона — это не «ноль урона», а неизвестность:
        берём rules.unknownDamage, иначе бой с безымянным ударом выглядел бы безопасным.
        """
        return average(self.damage) or tuning().unknown_damage_avg

    @property
    def sure_cells(self) -> float:
        return self.sure_ft / tuning().feet_per_cell

    @property
    def doubt_cells(self) -> float:
        return self.doubt_ft / tuning().feet_per_cell

    def mode_at(self, dist_cells: float) -> Optional[str]:
        """Режим попадания на дистанции dist_cells (клетки) — или None, если не достать."""
        t = tuning()
        feet = t.feet_per_cell
        # допуск тот же, что у within_reach: полклетки на диагональ/край токена
        if dist_cells <= self.sure_ft / feet + t.reach_tolerance:
            if (self.ranged and t.thrown_property not in self.properties
                    and dist_cells <= t.point_blank_cells + t.reach_tolerance):
                return DOUBT          # стрелять вплотную — только с помехой
            return SURE
        if dist_cells <= self.doubt_ft / feet + t.reach_tolerance:
            return DOUBT
        return None


def parse_weapons(raw: Optional[Iterable[Dict[str, Any]]]) -> Tuple[Weapon, ...]:
    """Список payload['weapons'] -> кортеж Weapon; записи без id отбрасываются."""
    t = tuning()
    out = []
    for entry in raw or []:
        wid = entry.get("id")
        if not wid:
            continue
        sure = float(entry.get("sureFt") or t.default_melee_ft)
        doubt = float(entry.get("doubtFt") or sure)
        doubt = max(sure, doubt)      # сомнительная не короче уверенной
        props = parse_properties(entry.get("properties"))
        ranged = entry.get("ranged")
        if ranged is None:
            # длинная дистанция бывает только у дальнобойного, но метательное — не он
            ranged = doubt > sure and t.thrown_property not in props
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

    Очки за зону берутся из points.json, поэтому «уверенная лучше сомнительной» —
    следствие настройки attack.sure > attack.doubt, а не жёсткого правила.
    При равных очках выбирается оружие с большим бонусом атаки.
    """
    t = tuning()
    best = None
    for weapon in weapons:
        mode = weapon.mode_at(dist_cells)
        if mode is None:
            continue
        points = t.attack_sure if mode == SURE else t.attack_doubt
        key = (points, weapon.attack_bonus)
        if best is None or key > best[0]:
            best = (key, weapon, mode)
    return (best[1], best[2]) if best else None
