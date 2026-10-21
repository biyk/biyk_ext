# arent/spec3.py — контракт SCHEMA=3: ход = позиция атаки × цель/оружие × позиция после атаки.
#
# v2 (spec.SCHEMA=2) кодирует ход одной клеткой = финальной: sim сворачивает все MOVE и бьёт
# из итоговой клетки, поэтому «выстрелить с места и отступить» невыразимо. v3 меняет ТОЛЬКО
# представление действия (голову клеток -> голову move-plan'ов (attack_cell, end_cell) в бюджете
# движения) и способ его исполнения (sim.apply_actor_seq: удар из текущей клетки). Вектор
# состояния (наблюдение) остаётся как в v2, чтобы не площить признаки; bump схемы обязателен,
# потому что меняется состав/размер головы клеток -> dims() отличается -> старые v2-веса net.load
# и rl_setup._guard_compat ОТКАЗЫВАЮТ с явной ошибкой (не молча). v2-код/модели/датасеты не
# трогаются: v3 живёт в отдельной схеме и отдельных артефактах.
from typing import Dict

from arent import spec

SCHEMA = 3

# Голова move-plan: пары (attack_cell, end_cell), достижимые в пределах бюджета хода.
# Последний слот — «не перемещаться» (атака/пропуск с исходной позиции).
K_MOVEPLAN = 48
K_TARGETS = spec.K_TARGETS          # цель/оружие/союзники/патч — как в v2
K_ALLIES = spec.K_ALLIES
K_WEAPONS = spec.K_WEAPONS
PATCH_R = spec.PATCH_R
PATCH_SIZE = spec.PATCH_SIZE
NONE_SLOT = spec.NONE_SLOT

# Признаки одного слота move-plan (порядок задаёт encode_v3.cell_vectors): позиция атаки и
# позиция после атаки (смещения от исходной клетки и дистанции), разбор бюджета, зоны удара
# из позиции атаки, и риск/укрытие в финальной позиции. cover/threat/los заполняет F-C.
CELL3_FEATURES: tuple = (
    "slotActive", "slotIndex",
    "adx", "ady", "adist",           # позиция атаки относительно исходной
    "edx", "edy", "edist",           # позиция после атаки относительно исходной
    "costIn", "costOut", "costTotal", "budgetFrac",
    "sureAttack", "doubtAttack", "canAttack",     # зона удара ИЗ attack_cell
    "stay", "pureMove", "retreatToOrigin", "gapIncrease",
    "coverFinal", "threatFinal", "losAttack",
)


def dims3() -> Dict[str, int]:
    """Размерности v3: state как в v2, но голова клеток — move-plan'ы с CELL3_FEATURES."""
    d = dict(spec.dims())
    d["schema"] = SCHEMA
    d["cells"] = K_MOVEPLAN + 1
    d["cell_feat"] = len(CELL3_FEATURES)
    return d
