# planner/pathfinding.py — сервис расчёта маршрута по сетке.
#
# Адаптер над libs/quin.py (A*, 4 направления, учёт стен и занятых клеток).
# Пункт 3 todo.md: API сервиса фиксируем и покрываем тестами; алгоритм
# (диагонали, стоимость движения, лимиты) развивается в пунктах 4–5.
from typing import List

from libs.quin import SimplePathfinder
from planner.context import BattleContext


class PathfindingService:
    """Сопоставляет id токенов с маршрутом из направлений движения."""

    def __init__(self, context: BattleContext):
        self._context = context
        self._finder = SimplePathfinder(context.raw)

    def find_path(self, src_id: str, tgt_id: str, mode: str = "direct") -> List[str]:
        """Список направлений ('up'/'down'/'left'/'right'); [] — маршрут невозможен."""
        try:
            return self._finder.find_path(src_id, tgt_id, mode)
        except KeyError:
            return []

    def path_to_target(self, mode: str = "direct") -> List[str]:
        """Маршрут от src-токена к целевому (payload.token). [] — цели нет или путь закрыт."""
        if not self._context.target_id:
            return []
        return self.find_path(self._context.src_id, self._context.target_id, mode)
