# arent/spec5.py — контракт SCHEMA=5: как v4 (move-plan + экномика + Ao) плюс голова манёвров.
#
# Новая 4-я голова «maneuver» кодирует выбор НЕ-атакующего действия (Dash/Disengage/Dodge).
# Семантика: манёвр стоит ACTION и потому mutually exclusive с атакой:
#   maneuver != NONE ⇒ weapon == NONE (⇒ target == NONE по канону).
#   maneuver == NONE ⇒ нормальное v4-поведение (атака или пропуск).
#
# Перенос весов v4->v5: ствол и старые головы копируются bit-for-bit; новая maneuver-голова
# инициализируется случайно (её ширина слота не влияет на существующие колонки).
# Хвост state не меняется (v4 уже содержит actionRemaining/bonusRemaining/reactionRemaining).
from typing import Dict

from arent import spec, spec4

SCHEMA = 5

# Версия признаков v5: своя нумерация (схема новая).
FEATURES_VERSION = 1

# ─── Голова манёвров ──────────────────────────────────────────────────────────────
# Три фиксированных манёвра + NONE-слот («без манёвра»).
K_MANEUVERS = 3            # dash, disengage, dodge
MANEUVER_NONE = K_MANEUVERS  # индекс NONE-слота (4-й, последний)
MANEUVER_KINDS = ("dash", "disengage", "dodge")

# Признаки одного слота манёвра (вектор ширины MANEUVER_FEATURES подаётся в Siamese-голову):
#   slotActive  — слот заполнен (не padding)
#   isDash / isDisengage / isDodge — one-hot идентичность манёвра
#   actionAvailable — у актёра осталось действие (нужно для исполнения манёвра)
MANEUVER_FEATURES: tuple = (
    "slotActive", "isDash", "isDisengage", "isDodge", "actionAvailable",
)

# ─── Остальное наследуется от v4 (те же ширины клеток/оружия/целей, тот же state) ───
CELL5_FEATURES: tuple = spec4.CELL4_FEATURES       # без изменений
WEAPON_FEATURES5: tuple = spec4.WEAPON_FEATURES4   # без изменений
RESOURCE_FEATURES: tuple = spec4.RESOURCE_FEATURES # без изменений

K_MOVEPLAN = spec4.K_MOVEPLAN
K_TARGETS = spec4.K_TARGETS
K_ALLIES = spec4.K_ALLIES
K_WEAPONS = spec4.K_WEAPONS
PATCH_R = spec4.PATCH_R
PATCH_SIZE = spec4.PATCH_SIZE
NONE_SLOT = spec4.NONE_SLOT


def dims5() -> Dict[str, int]:
    """Размерности v5:Dims v4 + новая группа «maneuvers».

    State не растёт (v4-хвост уже включает actionRemaining; availability манёвра кодируется
    в slot vector). Клетки/цели/оружие — та же ширина что в v4.
    """
    d = dict(spec4.dims4())
    d["schema"] = SCHEMA
    d["maneuvers"] = K_MANEUVERS + 1           # 4 слота (dash/disengage/dodge/NONE)
    d["maneuver_feat"] = len(MANEUVER_FEATURES)  # 5 признаков на слот
    d["feat_version"] = FEATURES_VERSION
    return d
