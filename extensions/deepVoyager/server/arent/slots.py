# arent/slots.py — пространство действий модели: куда встать × в кого бить × чем.
#
# Модель не выдумывает новые ходы: она выбирает из того же перебора, что и планировщик.
# Клетки берёт explore.reachable_paths (те же правила стен, занятых клеток и углов D&D
# 5e), цели — BattleContext.hostile_targets(), оружие — payload['weapons']. Поэтому
# ответ сети всегда декодируется в корректный список действий формата /plan, а разметка
# учителя гарантированно лежит внутри этого пространства (иначе пример отбрасывается).
#
# Три группы по одному индексу (cell, target, weapon) — это разложение одного выбора:
# жадный планировщик делает ровно то же (для каждой клетки лучшая атака по очкам).
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from planner.action import ACTION_MOVE, ACTION_TARGET, ACTION_USE, Action
from planner.action import move_action, target_action, use_action
from planner.context import BattleContext
from planner.explore import reachable_paths
from planner.geometry import Cell, apply_moves, cell_distance
from planner.pathfinding import PathfindingService
from arent import spec

TargetRef = Optional[str]


@dataclass
class Slots:
    """Слоты выбора: клетки (куда), цели (в кого), оружие (чем). Индексы = порядок списков."""
    cells: List[Dict[str, Any]] = field(default_factory=list)
    targets: List[Dict[str, Any]] = field(default_factory=list)
    weapons: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def n_cells(self) -> int:
        return len(self.cells)


def build(ctx: BattleContext, obs: Dict[str, Any]) -> Slots:
    """Наблюдение -> слоты: не более K_CELLS клеток, K_TARGETS целей, K_WEAPONS оружия."""
    pf = PathfindingService(ctx)._finder
    enemies = [e for e in obs["enemies"] if e["hostile"] and e["alive"]]
    paths = reachable_paths(pf, ctx.src_cell, ctx.src_id, ctx.speed_steps)
    # порядок: сначала короткие маршруты, среди них — ближе к врагу;
    # усечение по этому порядку оставляет «стоять на месте» и клетки у линии боя
    ordered = sorted(paths.items(),
                     key=lambda kv: (len(kv[1]), _nearest(kv[0], enemies, ctx), kv[0]))
    cells = [{"cell": cell, "dirs": dirs,
              "dx": cell[1] - ctx.src_cell[1], "dy": cell[0] - ctx.src_cell[0],
              "dist": round(cell_distance(ctx.src_cell, cell), 2)}
             for cell, dirs in ordered[:spec.K_CELLS]]
    targets = [e for e in enemies[:spec.K_TARGETS]]
    weapons = [w for w in obs["weapons"][:spec.K_WEAPONS]]
    return Slots(cells=cells, targets=targets, weapons=weapons)


def _nearest(cell: Cell, enemies: List[Dict[str, Any]], ctx: BattleContext) -> float:
    """Дистанция от клетки до ближайшего живого врага — по ней усекаем список до K_CELLS."""
    if not enemies:
        return 0.0
    return min(cell_distance(cell, _cell_of(ctx, e["id"])) for e in enemies)


def _cell_of(ctx: BattleContext, token_id: str) -> Cell:
    tok = ctx.token(token_id)
    return ctx.cell_of(tok) if tok else ctx.src_cell


def cell_index(slots: Slots, cell: Cell) -> int:
    """Индекс клетки в слотах; -1, если её там нет (клеток больше K_CELLS)."""
    return next((i for i, c in enumerate(slots.cells) if c["cell"] == cell), -1)


def ensure_cell(slots: Slots, src_cell: Cell, cell: Cell, dirs: List[str]) -> int:
    """Гарантировать клетку в слотах с маршрутом учителя; вернуть её индекс.

    Перебор усекается до K_CELLS по коротким маршрутам, а учитель иногда выбирает
    дальнюю клетку, чтобы отстреливаться, и без этого пример просто отбрасывался бы.
    Если мест нет — вытесняем последнюю клетку: она в порядке build наименее приоритетная.
    """
    entry = {"cell": cell, "dirs": list(dirs),
             "dx": cell[1] - src_cell[1], "dy": cell[0] - src_cell[0],
             "dist": round(cell_distance(src_cell, cell), 2)}
    index = cell_index(slots, cell)
    if index >= 0:
        slots.cells[index] = entry
        return index
    if len(slots.cells) >= spec.K_CELLS:
        slots.cells.pop()
    slots.cells.append(entry)
    return len(slots.cells) - 1


def attackable(slots: Slots, ctx: BattleContext, cell_i: int, target_i: int,
               weapon_i: int) -> bool:
    """Легально ли три: цель жива, клетка в слотах, оружие до цели достает."""
    if cell_i < 0 or target_i < 0 or weapon_i < 0:
        return False
    if not (0 <= cell_i < slots.n_cells):
        return False
    enemy = slots.targets[target_i]
    weapon = slots.weapons[weapon_i]
    if not enemy["alive"]:
        return False
    dist = cell_distance(slots.cells[cell_i]["cell"], _cell_of(ctx, enemy["id"]))
    return dist <= float(weapon["doubtCells"]) + 0.5


def decode(slots: Slots, label: Dict[str, int]) -> List[Action]:
    """Три индекса -> действия /plan: цель, затем шаги, затем атака (порядок как у планировщика).

    Индекс за пределами списка — это «не стрелять/не атаковать» (в выборке это последний
    слот группы), поэтому он не действие, а пропуск: -1 и total-1 означают одно и то же.
    """
    actions: List[Action] = []
    target_i = _real(label.get("target", spec.NONE_SLOT), len(slots.targets))
    weapon_i = _real(label.get("weapon", spec.NONE_SLOT), len(slots.weapons))
    cell_i = label.get("cell", 0)
    if target_i >= 0:
        actions.append(target_action(slots.targets[target_i]["id"]))
    if 0 <= cell_i < slots.n_cells:
        actions += [move_action(d) for d in slots.cells[cell_i]["dirs"]]
    if weapon_i >= 0:
        actions.append(use_action(slots.weapons[weapon_i]["id"]))
    return actions


def _real(index: int, count: int) -> int:
    """Индекс настоящего слота или -1, если выбран «пустой» слот группы."""
    return index if 0 <= index < count else -1


def dirs_of(actions: List[Action]) -> List[str]:
    """Направления движения из плана учителя (порядок сохраняется)."""
    return [a.conf.get("direction") for a in actions if a.action == ACTION_MOVE
            and a.conf.get("direction")]


def final_cell(ctx: BattleContext, actions: List[Action]) -> Cell:
    """Клетка, в которой учитель оказался после своих ходов."""
    return apply_moves(ctx.src_cell, dirs_of(actions))


def label_of(ctx: BattleContext, slots: Slots, actions: List[Action]) -> Optional[Dict[str, int]]:
    """План учителя -> три индекса; None, если финальная клетка не попала в слоты."""
    cell_i = cell_index(slots, final_cell(ctx, actions))
    if cell_i < 0:
        return None
    aimed = next((a.conf.get("id") for a in reversed(actions) if a.action == ACTION_TARGET), None)
    used = next((a.conf.get("itemId") for a in actions if a.action == ACTION_USE), None)
    target_i = next((i for i, t in enumerate(slots.targets) if t["id"] == aimed), spec.NONE_SLOT)
    weapon_i = next((i for i, w in enumerate(slots.weapons) if w["id"] == used), spec.NONE_SLOT)
    return {"cell": cell_i, "target": target_i, "weapon": weapon_i}
