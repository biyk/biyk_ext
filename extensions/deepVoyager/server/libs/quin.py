# libs/quin.py

import math
import heapq
from typing import List, Dict, Tuple

class SimplePathfinder:
    """Только ортогональные шаги (4 направления)."""

    def __init__(self, scene_data: dict):
        self.gs = scene_data["scene"]["gridSize"]
        self.cols = scene_data["scene"]["width"] // self.gs
        self.rows = scene_data["scene"]["height"] // self.gs

        # только стены, мешающие движению
        self.walls = []
        for w in scene_data["walls"]:
            if w.get("move", 0) > 0:
                self.walls.append((
                    (w["points"]["A"]["x"], w["points"]["A"]["y"]),
                    (w["points"]["B"]["x"], w["points"]["B"]["y"])
                ))

        # NPC: id → (row, col) и их прямоугольники
        self.npc_map: Dict[str, Tuple[int, int]] = {}
        self.npc_rects: Dict[str, Tuple[float,float,float,float]] = {}
        for npc in scene_data["npcs"]:
            r = int(npc["center"]["y"] // self.gs)
            c = int(npc["center"]["x"] // self.gs)
            self.npc_map[npc["id"]] = (r, c)
            self.npc_rects[npc["id"]] = (
                npc["x"], npc["y"], npc["width"], npc["height"]
            )

        # 4 направления
        self.dirs = [(-1,0), (1,0), (0,-1), (0,1)]
        self.dir_names = {
            (-1,0): "up",
            (1,0): "down",
            (0,-1): "left",
            (0,1): "right"
        }

    # -----------------------------------------------------------------
    def _center(self, r, c):
        return (c + 0.5) * self.gs, (r + 0.5) * self.gs

    def _cell_rect(self, r, c):
        return c * self.gs, r * self.gs, self.gs, self.gs

    @staticmethod
    def _segment_intersect(p1, p2, p3, p4) -> bool:
        def ccw(A, B, C):
            return (C[1]-A[1])*(B[0]-A[0]) - (B[1]-A[1])*(C[0]-A[0])
        d1 = ccw(p1, p2, p3)
        d2 = ccw(p1, p2, p4)
        d3 = ccw(p3, p4, p1)
        d4 = ccw(p3, p4, p2)
        return (d1 > 0 and d2 < 0 or d1 < 0 and d2 > 0) and \
               (d3 > 0 and d4 < 0 or d3 < 0 and d4 > 0)

    @staticmethod
    def _segment_rect_intersect(ax, ay, bx, by, rx, ry, rw, rh) -> bool:
        min_x, max_x = min(ax, bx), max(ax, bx)
        min_y, max_y = min(ay, by), max(ay, by)
        if max_x <= rx or min_x >= rx+rw or max_y <= ry or min_y >= ry+rh:
            return False
        edges = [
            (rx, ry, rx+rw, ry), (rx+rw, ry, rx+rw, ry+rh),
            (rx+rw, ry+rh, rx, ry+rh), (rx, ry+rh, rx, ry)
        ]
        for ex1, ey1, ex2, ey2 in edges:
            if SimplePathfinder._segment_intersect((ax, ay), (bx, by), (ex1, ey1), (ex2, ey2)):
                return True
        return False

    @staticmethod
    def _rect_rect_overlap(x1, y1, w1, h1, x2, y2, w2, h2) -> bool:
        return x1 < x2 + w2 and x1 + w1 > x2 and y1 < y2 + h2 and y1 + h1 > y2

    # -----------------------------------------------------------------
    def _cell_valid(self, r, c, ignore_npc_id: str = None) -> bool:
        """Клетка свободна для занятия (без учёта лучей)."""
        x, y, w, h = self._cell_rect(r, c)
        # границы
        if x < 0 or y < 0 or x + w > self.cols * self.gs or y + h > self.rows * self.gs:
            return False
        # стены
        for seg in self.walls:
            if self._segment_rect_intersect(seg[0][0], seg[0][1], seg[1][0], seg[1][1], x, y, w, h):
                return False
        # другие NPC
        for nid, (rx, ry, rw, rh) in self.npc_rects.items():
            if nid == ignore_npc_id:
                continue
            if self._rect_rect_overlap(x, y, w, h, rx, ry, rw, rh):
                return False
        return True

    def _edge_valid(self, r1, c1, r2, c2, ignore_npc_id: str = None) -> bool:
        """Переход центра из клетки в клетку (отрезок не пересекает стены и NPC)."""
        p1 = self._center(r1, c1)
        p2 = self._center(r2, c2)
        # стены
        for seg in self.walls:
            if self._segment_intersect(p1, p2, seg[0], seg[1]):
                return False
        # NPC
        for nid, (rx, ry, rw, rh) in self.npc_rects.items():
            if nid == ignore_npc_id:
                continue
            if self._segment_rect_intersect(p1[0], p1[1], p2[0], p2[1], rx, ry, rw, rh):
                return False
        return True

    def _has_los(self, r1, c1, r2, c2) -> bool:
        p1 = self._center(r1, c1)
        p2 = self._center(r2, c2)
        for seg in self.walls:
            if self._segment_intersect(p1, p2, seg[0], seg[1]):
                return False
        return True

    # -----------------------------------------------------------------
    def find_path(self, src_id: str, tgt_id: str, mode: str = "direct") -> List[str]:
        if src_id not in self.npc_map or tgt_id not in self.npc_map:
            raise KeyError("Source or Target ID not found")
        start = self.npc_map[src_id]
        end   = self.npc_map[tgt_id]

        # стартовая клетка должна быть свободна (игнорируем самого себя)
        if not self._cell_valid(start[0], start[1], ignore_npc_id=src_id):
            return []

        open_set = [(0.0, 0.0, start)]
        came_from: Dict[Tuple[int,int], Tuple[int,int]] = {}
        g_score = {start: 0.0}

        while open_set:
            f, g, (cr, cc) = heapq.heappop(open_set)
            if g > g_score.get((cr, cc), math.inf):
                continue

            if mode == "direct" and (cr, cc) == end:
                if self._cell_valid(cr, cc, ignore_npc_id=tgt_id):
                    return self._reconstruct(came_from, (cr, cc))
                continue
            if mode == "los" and self._has_los(cr, cc, end[0], end[1]):
                return self._reconstruct(came_from, (cr, cc))

            for dr, dc in self.dirs:
                nr, nc = cr + dr, cc + dc
                if not (0 <= nr < self.rows and 0 <= nc < self.cols):
                    continue

                # конечная клетка
                ign_cell = tgt_id if (nr, nc) == end else None
                if not self._cell_valid(nr, nc, ign_cell):
                    continue

                # ребро перехода
                ign_edge = src_id if (cr, cc) == start else (tgt_id if (nr, nc) == end else None)
                if not self._edge_valid(cr, cc, nr, nc, ign_edge):
                    continue

                cost = 1.0   # все шаги равны
                tent_g = g + cost
                if tent_g < g_score.get((nr, nc), math.inf):
                    came_from[(nr, nc)] = (cr, cc)
                    g_score[(nr, nc)] = tent_g
                    # Манхэттенская эвристика (без диагоналей)
                    h = abs(nr - end[0]) + abs(nc - end[1])
                    heapq.heappush(open_set, (tent_g + h, tent_g, (nr, nc)))

        return []

    def _reconstruct(self, came_from, cur):
        path = [cur]
        while cur in came_from:
            cur = came_from[cur]
            path.append(cur)
        path.reverse()
        return self._to_dirs(path)

    def _to_dirs(self, path):
        return [self.dir_names[(path[i+1][0]-path[i][0], path[i+1][1]-path[i][1])]
                for i in range(len(path)-1)]


def find_path_from_data(request: dict) -> List[str]:

    src_id = request.get("src")
    tgt_id = request.get("token")
    scene_data = request.get("data")
    mode = request.get("mode", "direct")
    if not src_id or not tgt_id or not scene_data:
        raise ValueError("Missing required fields")
    pf = SimplePathfinder(scene_data)
    return pf.find_path(src_id, tgt_id, mode)