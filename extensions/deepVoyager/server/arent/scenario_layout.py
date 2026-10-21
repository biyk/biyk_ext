# arent/scenario_layout.py — геометрия сцены: профили поля, узоры стен, зоны расстановки.
#
# Отвечает ровно за «где что стоит»: размеры поля, узор стен, две зоны deployment и
# размещение обеих команд (с джиттером или без). Состав/классы/оружие — в scenarios.py.
# Всё детерминировано переданным rng: один seed -> та же карта и те же стартовые клетки.
# Детерминизм критичен для честного A/B: учитель и политика обязаны видеть ИДЕНТИЧНЫЙ
# сценарий, иначе сравнение ходов теряет смысл (память: Independent Evaluation Protocol).
import random
from typing import Dict, List, Sequence, Tuple

Cell = Tuple[int, int]
Offset = Tuple[int, int]

GRID = 50            # px в клетке (=футов): rows = height_px // GRID
MARGIN = 2           # защитная рамка: юниты не ставим вплотную к краю

# Профили поля: [min,max] клеток по оси; вероятность small/medium/large = .25/.5/.25.
FIELD_PROFILES: Sequence[Tuple[str, int, int]] = (
    ("small", 14, 16), ("medium", 18, 24), ("large", 26, 32),
)
FIELD_WEIGHTS: Sequence[float] = (0.25, 0.5, 0.25)

# Профили стен выбираются по seed НЕЗАВИСИМО от архетипа (число сегментов 0..20).
WALL_PROFILES: Sequence[str] = ("open", "scatter", "pillars", "corridor", "ring", "maze_lite")
_WALL_BUDGET: Dict[str, int] = {"open": 0, "scatter": 5, "pillars": 16,
                                 "corridor": 12, "ring": 14, "maze_lite": 20}

DEPLOYMENTS: Sequence[str] = ("edge", "corner", "diagonal")

# Относительные построения вокруг якоря команды (строка, столбец) — по 6, состав <=6.
LINE: Sequence[Offset] = ((0, -3), (0, -1), (0, 0), (0, 1), (0, 3), (1, 0))
RING: Sequence[Offset] = ((0, 0), (-1, -2), (1, -2), (-1, 2), (1, 2), (0, 3))
PINCER: Sequence[Offset] = ((0, -3), (0, 3), (0, 0), (0, -2), (0, 2), (-2, 0))
CROSS: Sequence[Offset] = ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1), (2, 0))
DIAG: Sequence[Offset] = ((0, 0), (-1, -1), (1, 1), (-1, 1), (1, -1), (-2, -2))
CLUSTER: Sequence[Offset] = ((0, 0), (0, 1), (1, 0), (0, -1), (-1, 0), (1, 1))
FORMATIONS: Dict[str, Sequence[Offset]] = {
    "line": LINE, "ring": RING, "pincer": PINCER, "cross": CROSS, "diag": DIAG,
}


def pick_field(rng: random.Random) -> Tuple[str, int, int]:
    """(profile, rows, cols): профиль по весам, стороны независимо в диапазоне профиля."""
    roll = rng.random()
    acc = 0.0
    profile = FIELD_PROFILES[-1]
    for i, w in enumerate(FIELD_WEIGHTS):
        acc += w
        if roll <= acc:
            profile = FIELD_PROFILES[i]
            break
    _, lo, hi = profile
    rows = rng.randint(lo, hi)
    cols = rng.randint(lo, hi)
    return profile[0], rows, cols


def pick_wall_profile(rng: random.Random) -> str:
    """Профиль стен — равномерный выбор, независимый от архетипа."""
    return rng.choice(list(WALL_PROFILES))


def _edge_v(r: int, c: int) -> Dict[str, Dict[str, int]]:
    x = (c + 1) * GRID
    return {"A": {"x": x, "y": r * GRID}, "B": {"x": x, "y": (r + 1) * GRID}}


def _edge_h(r: int, c: int) -> Dict[str, Dict[str, int]]:
    y = (r + 1) * GRID
    return {"A": {"x": c * GRID, "y": y}, "B": {"x": (c + 1) * GRID, "y": y}}


def _candidates(profile: str, rows: int, cols: int, rng: random.Random) -> List[Dict]:
    """Сырые сегменты стены для профиля (до срезки бюджетом); каждый — points A/B в px."""
    out: List[Dict] = []

    def push(edge, sight):
        out.append({"points": edge, "move": 1, "sight": sight})

    if profile == "scatter":                       # случайные короткие сегменты в теле поля
        for _ in range(_WALL_BUDGET["scatter"] * 2):
            r = rng.randint(1, max(1, rows - 2)); c = rng.randint(1, max(1, cols - 2))
            push(_edge_v(r, c) if rng.random() < 0.5 else _edge_h(r, c), int(rng.random() < 0.5))
    elif profile == "pillars":                     # 1-4 квадратных блока по 4 грани
        for _ in range(rng.randint(1, 4)):
            r = rng.randint(1, max(1, rows - 2)); c = rng.randint(1, max(1, cols - 2))
            for e in (_edge_v(r, c - 1), _edge_v(r, c), _edge_h(r - 1, c), _edge_h(r, c)):
                push(e, 1)
    elif profile == "corridor":                     # 2 продольные стены с разрывом посередине
        col = rng.randint(cols // 3, max(cols // 3, 2 * cols // 3))
        gap = rows // 2
        for r in range(1, rows - 1):
            if abs(r - gap) <= 1:
                continue
            push(_edge_v(r, col - 1), 1)
    elif profile == "ring":                        # прямоугольник-кольцо вокруг центра с разрывом
        m = 2
        top, bot, lf, rt = m, rows - 1 - m, m, cols - 1 - m
        for c in range(lf, rt):
            push(_edge_h(top - 1, c), 1)
        for c in range(lf, rt):
            if c != rt - 1:                         # разрыв для прохода
                push(_edge_h(bot - 1, c), 1)
        for r in range(top, bot):
            push(_edge_v(r, lf - 1), 1)
    elif profile == "maze_lite":                    # решётка с случайными проёмами
        for r in range(1, rows - 1):
            for c in range(1, cols - 1):
                if r % 2 == 0 and rng.random() < 0.5:
                    push(_edge_h(r - 1, c), 1)
                if c % 2 == 0 and rng.random() < 0.5:
                    push(_edge_v(r, c - 1), 1)
    return out


def build_walls(rng: random.Random, profile: str, rows: int, cols: int) -> List[Dict]:
    """Сегменты стен профиля, срезанные бюджетом 0..20; координаты внутри поля."""
    cands = _candidates(profile, rows, cols, rng)
    budget = _WALL_BUDGET.get(profile, 0)
    if budget <= 0 or not cands:
        return []
    seen, uniq = set(), []
    for w in cands:                                  # убираем дубликаты граней (одна стена = сегмент)
        key = tuple(sorted((tuple(sorted(w["points"]["A"].items())),
                            tuple(sorted(w["points"]["B"].items())))))
        if key in seen:
            continue
        seen.add(key)
        uniq.append({"id": f"w{len(uniq)}", "points": w["points"],
                     "move": w["move"], "sight": w["sight"]})
    return uniq if len(uniq) <= budget else rng.sample(uniq, budget)


def anchors(mode: str, rows: int, cols: int) -> Tuple[Cell, Cell]:
    """Якоря двух команд (свои, враги) для выбранного режима расстановки."""
    if mode == "edge":
        return (MARGIN, cols // 2), (rows - 1 - MARGIN, cols // 2)
    if mode == "corner":
        return (MARGIN, MARGIN), (rows - 1 - MARGIN, cols - 1 - MARGIN)
    return (MARGIN, cols - 1 - MARGIN), (rows - 1 - MARGIN, MARGIN)   # diagonal


def _in(r: int, c: int, rows: int, cols: int) -> bool:
    return MARGIN <= r <= rows - 1 - MARGIN and MARGIN <= c <= cols - 1 - MARGIN


def _find_free(cell: Cell, rows: int, cols: int, occ: set) -> Cell:
    """Ближайшая свободная клетка в рамке (спиралью), чтобы команды не наслаивались."""
    r, c = cell
    if _in(r, c, rows, cols) and (r, c) not in occ:
        return (r, c)
    for rad in range(1, rows + cols):
        for dr in range(-rad, rad + 1):
            for dc in range(-rad, rad + 1):
                if max(abs(dr), abs(dc)) != rad:
                    continue
                if _in(r + dr, c + dc, rows, cols) and (r + dr, c + dc) not in occ:
                    return (r + dr, c + dc)
    return cell


def _team_cells(rng, anchor: Cell, offsets: Sequence[Offset], count: int,
               rows: int, cols: int, jitter: int, occ: set) -> List[Cell]:
    cells: List[Cell] = []
    for i in range(count):
        dr, dc = offsets[i] if i < len(offsets) else (0, 0)
        r, c = anchor[0] + dr, anchor[1] + dc
        if jitter:
            r += rng.randint(-jitter, jitter)
            c += rng.randint(-jitter, jitter)
        r = max(MARGIN, min(rows - 1 - MARGIN, r))
        c = max(MARGIN, min(cols - 1 - MARGIN, c))
        cell = _find_free((r, c), rows, cols, occ)
        occ.add(cell)
        cells.append(cell)
    return cells


def place(rng: random.Random, rows: int, cols: int, n_ours: int, off_ours: Sequence[Offset],
          n_foes: int, off_foes: Sequence[Offset], mode: str, jitter: int
          ) -> Tuple[List[Cell], List[Cell], str]:
    """Клетки обеих команд: якоря по режиму, построение по offset, опц. джиттер ±j."""
    a_ours, a_foes = anchors(mode, rows, cols)
    occ: set = set()
    ours = _team_cells(rng, a_ours, off_ours, n_ours, rows, cols, jitter, occ)
    foes = _team_cells(rng, a_foes, off_foes, n_foes, rows, cols, jitter, occ)
    return ours, foes, mode
