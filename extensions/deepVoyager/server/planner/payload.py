# planner/payload.py — токен сцены и разбор npcs[] сырого запроса.
#
# Формат — api.getAllData() со стороны Foundry (extensions/deepVoyager/index.js):
# npcs[] = [{id, name, x, y, width, height, center, disposition, hp}, ...].
# Пункт 5 добавляет необязательные speed/damage/reachFt/hitChance — параметры,
# нужные для симуляции чужих ходов. Старый клиент их не присылает, и сервер берёт
# дефолты из points.json, поэтому контракт /plan остаётся прежним.
# Модель боя и её методы — в planner/context.py; здесь только «данные -> объекты».
from dataclasses import dataclass
from typing import Any, Dict, List

from planner.dice import average
from planner.points import tuning


@dataclass(frozen=True)
class Token:
    """Один токен сцены: геометрия для раскладки плюс параметры для симуляции хода."""
    id: str
    x: int
    y: int
    width: int
    height: int
    center_x: float
    center_y: float
    disposition: int
    hp_current: int
    name: str = ""          # имя из Foundry — только для логов, на решения не влияет
    speed_ft: int = 0       # футов за ход; 0 = «не прислано»
    damage: str = ""        # строка кубика («1d8»); "" = «не прислано»
    reach_ft: float = 0.0   # досягаемость его атаки
    hit_chance: float = 0.0  # вероятность попадания; 0 = «не прислано»

    @property
    def is_alive(self) -> bool:
        return self.hp_current > 0

    @property
    def sim_speed_steps(self) -> int:
        """Клеток за ход: своё поле speed или rules.defaultSpeedFt."""
        t = tuning()
        return int((self.speed_ft or t.default_speed_ft) // t.feet_per_cell)

    @property
    def sim_reach_cells(self) -> float:
        """Досягаемость атаки в клетках; без данных — rules.defaultEnemyReachFt."""
        t = tuning()
        return self.reach_ft / t.feet_per_cell if self.reach_ft else t.default_enemy_reach_cells

    @property
    def sim_damage_avg(self) -> float:
        """Ожидание урона; пустая или неразбираемая строка — rules.unknownDamage, не ноль."""
        return average(self.damage) or tuning().unknown_damage_avg

    @property
    def sim_hit_chance(self) -> float:
        """Вероятность попадания; 0 читается как «КД не прислали» -> rules.hitChance."""
        return self.hit_chance or tuning().hit_chance


def _number(value: Any, as_int: bool = True) -> Any:
    """Число из payload; мусор (строка/None/отсутствие) — 0, то есть «данных нет»."""
    try:
        return int(float(value)) if as_int else float(value)
    except (TypeError, ValueError):
        return 0 if as_int else 0.0


def parse_tokens(data: Dict[str, Any]) -> List[Token]:
    """data['npcs'] -> токены; ни одного токена — ошибка входа (HTTP 400)."""
    out = []
    for n in data.get("npcs") or []:
        hp = n.get("hp") or {}
        center = n.get("center") or {}
        out.append(Token(
            id=n["id"],
            x=int(n["x"]), y=int(n["y"]),
            width=int(n["width"]), height=int(n["height"]),
            center_x=float(center.get("x", n["x"] + n["width"] / 2)),
            center_y=float(center.get("y", n["y"] + n["height"] / 2)),
            disposition=int(n.get("disposition", 0)),
            hp_current=int(hp.get("current", 0)),
            name=str(n.get("name") or ""),
            speed_ft=_number(n.get("speed")),
            damage=str(n.get("damage") or ""),
            reach_ft=_number(n.get("reachFt"), as_int=False),
            hit_chance=_number(n.get("hitChance"), as_int=False),
        ))
    if not out:
        raise ValueError("No tokens in scene data")
    return out
