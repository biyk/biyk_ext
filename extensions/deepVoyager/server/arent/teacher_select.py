# arent/teacher_select.py — «сильнейший учитель в роли» для DAgger-разметки посещённых состояний.
#
# §Выбор пользователя (этап "учимся на действиях учителя"): в каждом посещённом состоянии ход
# берёт тот учитель, что сильнее в РОЛИ текущего актёра. Честный замер (.ray/measure_role_teacher.py:
# greedy vs battlecast, весь stage3-пуль, обе расстановки сторон) показал battlecast не хуже greedy
# ни в одной производной роли -> по текущим данным таблица сводится к battlecast. Механизм остаётся
# табличным: future-замер, разведший роли, правит только DEFAULT_ROLE_TEACHER (или подаёт свой table).
#
# Роль — производная (не класс генератора): ranged / melee / tank, ровно как в tactics_ctx
# (_is_ranged по reach>=3, танк по hp>=24), потому что на живом состоянии у нас есть только reach/hp.
from typing import Dict, Optional

RANGE_MIN_CELLS = 3.0     # синхронно с tactics_ctx.RANGE_MIN_CELLS
TANK_HP_MIN = 24.0        # синхронно с tactics_ctx.TANK_HP_MIN
FALLBACK_TEACHER = "battlecast"      # сильнейший в целом по замеру -> разумный default при промахе роли

# роль -> имя учителя из реестра (arent.teachers). Итог замера: battlecast доминирует все роли.
DEFAULT_ROLE_TEACHER: Dict[str, str] = {
    "ranged": "battlecast",
    "melee": "battlecast",
    "tank": "battlecast",
}


def derive_role(reach_cells: float, hp_max: float) -> str:
    """Производная роль бойца по ground-truth-признакам (совпадает с tactics_ctx._derive_role)."""
    if float(reach_cells) >= RANGE_MIN_CELLS:
        return "ranged"
    return "tank" if float(hp_max) >= TANK_HP_MIN else "melee"


def teacher_for_role(role: str, table: Optional[Dict[str, str]] = None) -> str:
    """Имя сильнейшего учителя для роли; неизвестная роль -> fallback (сильнейший в целом)."""
    return (table or DEFAULT_ROLE_TEACHER).get(role, FALLBACK_TEACHER)


def measured_table(tally: Dict[str, Dict[str, int]]) -> Dict[str, str]:
    """Свернуть tally «роль -> {учитель: побед}» в таблицу «роль -> сильнейший учитель».

    Ничья (равное число побед) отдаётся более сильному в целом (FALLBACK_TEACHER), чтобы не
    флипаться от шума: при равенстве берём доминирующего по общему замеру учителя.
    """
    out: Dict[str, str] = {}
    for role, wins in tally.items():
        best, best_n = None, -1
        for teacher, n in wins.items():
            if n > best_n:
                best, best_n = teacher, n
            elif n == best_n and teacher == FALLBACK_TEACHER:
                best = teacher                       # ничья -> сильнейший в целом
        out[role] = best or FALLBACK_TEACHER
    return out
