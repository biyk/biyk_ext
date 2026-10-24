# arent/tactics_geom.py — геометрия укрытий и узостей для тактик Этапа 4 (§Этап 4).
#
# Два независимых, чистых от симуляции факта о КАРТЕ, общие для наблюдения (encode_v3) и
# детекторов (tactics_ctx), чтобы «что видит сеть» и «что засчитает детектор» не расходились:
#
#   enemy_cover(ctx, cell, foes) — укрыт ли cell от ВСЕХ врагов линиями огня (стены sight).
#     Ровно семантика cover_shoot/cover_after: ни один враг не стреляет сюда без пролома LOS.
#   chokepoint_cells(ctx) / is_choke(ctx, cell) — узости поля: артикуляционные точки графа
#     проходимости (4-связность; move-стены и границы режут рёбра). Удаление узости разъединяет
#     регион -> через неё идут по одному (проём в кольце, дверь лабиринта). Открытый пролёт
#     шириной >=2 клеток узостью НЕ считается (снять одну клетку => всё ещё проходят).
#
# Всё детерминировано геометрией ctx (walls+размер), НЕ позициями токенов: chokepoint — свойство
# карты, поэтому кэшируется по подписи стен. is_choke для большой сетки даёт артикуляцию графа,
# совпадающую с тем, что видит A* (8 направлений) по ортогональным переходам — диагонали здесь
# сознательно не соединяем: однофайловый проход определяется ортогональной дверью.
from typing import Dict, List, Optional, Sequence, Tuple

from libs.quin import SimplePathfinder
from planner.context import BattleContext
from planner.geometry import Cell
from planner.los import has_los, sight_segments

ORTHO: Tuple[Tuple[int, int], ...] = ((-1, 0), (1, 0), (0, -1), (0, 1))
Point = Tuple[float, float]
Segment = Tuple[Point, Point]

_CACHE: Dict[Tuple, frozenset] = {}


def _center(ctx: BattleContext, cell: Cell) -> Point:
    gs = ctx.scene.grid_size
    return (cell[1] + 0.5) * gs, (cell[0] + 0.5) * gs


def _crosses(a: Cell, b: Cell, segments: Sequence[Segment], ctx: BattleContext) -> bool:
    """Пересекает ли прямая между центрами клеток a..b хоть один сегмент стены."""
    p1, p2 = _center(ctx, a), _center(ctx, b)
    return any(SimplePathfinder._segment_intersect(p1, p2, s[0], s[1]) for s in segments)


def enemy_cover(ctx: BattleContext, cell: Cell, foes_cells: Sequence[Cell],
                segments: Optional[List[Segment]] = None) -> bool:
    """Укрыта ли клетка от всех врагов: ни у одного нет линии видимости (сight-стены)."""
    foes = [f for f in foes_cells if f is not None]
    if not foes:
        return False
    seg = sight_segments(ctx) if segments is None else segments
    return not any(has_los(ctx, cell, f, seg) for f in foes)


def _move_segments(ctx: BattleContext) -> List[Segment]:
    return [((w.ax, w.ay), (w.bx, w.by)) for w in ctx.walls if w.move > 0]


def _signature(ctx: BattleContext) -> Tuple:
    mw = tuple(sorted((min(w.ax, w.bx), min(w.ay, w.by), max(w.ax, w.bx), max(w.ay, w.by))
                      for w in ctx.walls if w.move > 0))
    return (ctx.scene.rows, ctx.scene.cols, mw)


def _articulation_points(adj: List[List[int]]) -> List[int]:
    """Итеративный Тарьян: индексы шарнирных точек недиректированного графа смежности."""
    n = len(adj)
    disc = [-1] * n
    low = [0] * n
    parent = [-1] * n
    ap = [False] * n
    time = 0
    for start in range(n):
        if disc[start] != -1:
            continue
        disc[start] = low[start] = time
        time += 1
        stack = [[start, 0]]
        root_children = 0
        while stack:
            u, ci = stack[-1]
            if ci < len(adj[u]):
                stack[-1][1] += 1
                v = adj[u][ci]
                if disc[v] == -1:
                    parent[v] = u
                    if u == start:
                        root_children += 1
                    disc[v] = low[v] = time
                    time += 1
                    stack.append([v, 0])
                elif v != parent[u]:
                    low[u] = min(low[u], disc[v])
            else:
                stack.pop()
                if stack:
                    p = stack[-1][0]
                    low[p] = min(low[p], low[u])
                    if parent[p] != -1 and low[u] >= disc[p]:
                        ap[p] = True
        if root_children > 1:
            ap[start] = True
    return [i for i in range(n) if ap[i]]


def chokepoint_cells(ctx: BattleContext) -> frozenset:
    """Клетки-узости карты (артикуляционные точки графа проходимости). Кэш по подписи стен."""
    key = _signature(ctx)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    rows, cols = ctx.scene.rows, ctx.scene.cols
    move_segs = _move_segments(ctx)
    cells = [(r, c) for r in range(rows) for c in range(cols)]
    idx = {cell: i for i, cell in enumerate(cells)}
    adj: List[List[int]] = [[] for _ in cells]
    for (r, c) in cells:
        for dr, dc in ORTHO:
            nb = (r + dr, c + dc)
            if not (0 <= nb[0] < rows and 0 <= nb[1] < cols):
                continue
            if move_segs and _crosses((r, c), nb, move_segs, ctx):
                continue
            adj[idx[(r, c)]].append(idx[nb])
    result = frozenset(cells[i] for i in _articulation_points(adj))
    _CACHE[key] = result
    return result


def is_choke(ctx: BattleContext, cell: Cell) -> bool:
    return cell in chokepoint_cells(ctx)
