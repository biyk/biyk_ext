# planner/context.py — доменная модель боевой ситуации.
#
# Строится из payload эндпоинтов /plan и /path — это формат api.getAllData()
# со стороны Foundry (extensions/deepVoyager/index.js):
# { src, token, data: { scene: {...}, npcs: [...], walls: [...] } }
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


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

    def token(self, token_id: str) -> Optional[Token]:
        return next((t for t in self.tokens if t.id == token_id), None)

    @property
    def src(self) -> Token:
        t = self.token(self.src_id)
        if t is None:
            raise ValueError(f"Src-токен не найден в данных сцены: {self.src_id!r}")
        return t

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
        )
