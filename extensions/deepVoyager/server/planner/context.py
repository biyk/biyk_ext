# planner/context.py — доменная модель боевой ситуации.
#
# Строится из payload эндпоинтов /plan и /path — это формат api.getAllData()
# со стороны Foundry (extensions/deepVoyager/index.js):
# { src, token, data: { scene: {...}, npcs: [...], walls: [...] } }
# Опциональные поля шага 4: speed (футы за ход) и weapons (массив вооружения,
# см. planner/armament.py — дальности уверенного/сомнительного попадания).
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from planner.armament import Weapon, parse_weapons
from planner.geometry import Cell
from planner.points import tuning


@dataclass(frozen=True)
class Scene:
    height_px: int
    width_px: int
    grid_size: int

    @property
    def cols(self) -> int:
        return self.width_px // self.grid_size

    @property
    def rows(self) -> int:
        return self.height_px // self.grid_size

    def cell_of(self, x: float, y: float) -> Tuple[int, int]:
        """(row, col) клетки, содержащей точку (x, y) в пикселях."""
        return int(y // self.grid_size), int(x // self.grid_size)


@dataclass(frozen=True)
class Token:
    id: str
    x: int
    y: int
    width: int
    height: int
    center_x: float
    center_y: float
    disposition: int
    hp_current: int
    name: str = ""      # имя из Foundry — только для логов, на решения не влияет

    @property
    def is_alive(self) -> bool:
        return self.hp_current > 0


@dataclass(frozen=True)
class Wall:
    ax: int
    ay: int
    bx: int
    by: int
    move: int
    sight: int

    @property
    def blocks_movement(self) -> bool:
        # В данных Foundry move: 0 = нет стены, > 0 — блокирует движение
        return self.move > 0


@dataclass(frozen=True)
class BattleContext:
    """Иммутабельный снимок поля боя + ссылки на участников хода."""
    scene: Scene
    tokens: Tuple[Token, ...]
    walls: Tuple[Wall, ...]
    src_id: str
    target_id: Optional[str]
    raw: Dict[str, Any]  # исходный payload.data — для адаптеров (libs.quin)
    speed_steps: int = 6           # шагов (клеток) за ход: speed_ft / rules.feetPerCell
    weapons: Tuple[Weapon, ...] = ()  # чем атаковать; пусто — атаки нет

    def token(self, token_id: str) -> Optional[Token]:
        return next((t for t in self.tokens if t.id == token_id), None)

    def weapon(self, weapon_id: str) -> Optional[Weapon]:
        """Оружие по itemId из действия use (None, если такого нет)."""
        return next((w for w in self.weapons if w.id == weapon_id), None)

    @property
    def src(self) -> Token:
        t = self.token(self.src_id)
        if t is None:
            raise ValueError(f"Src-токен не найден в данных сцены: {self.src_id!r}")
        return t

    def cell_of(self, token: Token) -> Cell:
        return self.scene.cell_of(token.center_x, token.center_y)

    @property
    def src_cell(self) -> Cell:
        return self.cell_of(self.src)

    def is_hostile(self, t: Token) -> bool:
        """Враждебен ли токен текущему (правила группировки как в utils/combat.js).

        Нейтральные (disposition 0) не воюют; для -2 (босс) друзья — это -1.
        """
        s = self.src.disposition
        if t.id == self.src_id or not t.is_alive:
            return False
        if s == 0 or t.disposition == 0:
            return False
        if s == -2:
            return t.disposition == 1
        return t.disposition != s

    def hostile_targets(self) -> List[Token]:
        """Живые враги + явный target_id из запроса (если это не src и он жив)."""
        result = [t for t in self.tokens if self.is_hostile(t)]
        if self.target_id and self.target_id != self.src_id:
            explicit = self.token(self.target_id)
            if explicit is not None and explicit.is_alive and explicit not in result:
                result.append(explicit)
        return result

    # ------------------------------------------------------------------
    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "BattleContext":
        """Валидация и разбор запроса. ValueError — на некорректный вход (HTTP 400)."""
        if not payload:
            raise ValueError("Missing JSON body")
        src_id = payload.get("src")
        data = payload.get("data")
        if not src_id or not data:
            raise ValueError("Missing required fields")

        scene_raw = data.get("scene") or {}
        if not scene_raw.get("gridSize"):
            raise ValueError("Missing scene.gridSize")
        scene = Scene(
            height_px=int(scene_raw["height"]),
            width_px=int(scene_raw["width"]),
            grid_size=int(scene_raw["gridSize"]),
        )

        tokens = []
        for n in data.get("npcs") or []:
            hp = n.get("hp") or {}
            center = n.get("center") or {}
            tokens.append(Token(
                id=n["id"],
                x=int(n["x"]), y=int(n["y"]),
                width=int(n["width"]), height=int(n["height"]),
                center_x=float(center.get("x", n["x"] + n["width"] / 2)),
                center_y=float(center.get("y", n["y"] + n["height"] / 2)),
                disposition=int(n.get("disposition", 0)),
                hp_current=int(hp.get("current", 0)),
                name=str(n.get("name") or ""),
            ))
        if not tokens:
            raise ValueError("No tokens in scene data")

        walls = []
        for w in data.get("walls") or []:
            pts = w.get("points") or {}
            a, b = pts.get("A"), pts.get("B")
            if not a or not b:
                raise ValueError(f"Wall {w.get('id')} has no A/B points")
            walls.append(Wall(
                ax=int(a["x"]), ay=int(a["y"]),
                bx=int(b["x"]), by=int(b["y"]),
                move=int(w.get("move") or 0), sight=int(w.get("sight") or 0),
            ))

        return cls(
            scene=scene, tokens=tuple(tokens), walls=tuple(walls),
            src_id=src_id, target_id=payload.get("token"), raw=data,
            speed_steps=int(float(payload.get("speed") or 30) // tuning().feet_per_cell),
            weapons=parse_weapons(payload.get("weapons")),
        )
