# arent/spec4.py — контракт SCHEMA=4: как v3 (move-plan), но с экномикой действий и Ao-реакцией.
#
# Семантика ДЕЙСТВИЯ (тройка план-атаки × цель × оружие) и голова move-plan НЕ меняются
# относительно v3 — меняется ТОЛЬКО состав/ширина ПРИЗНАКОВ:
#   1) ХВОСТ state — блок ресурсов хода актёра (action/bonus/reaction remaining) ПОСЛЕ grid:
#      старые колонки state (me|enemies|allies|weapons|grid) стоят на своих местах, поэтому
#      перенос весов v3->v4 = copy[:, :old_state] + zeros[:, old_state:new_state] (trunk1).
#   2) head-векторы слотов ДОПИСУВАЮТСЯ В КОНЕЦ слота (перестановочно-инвариантная Siamese
#      голова, как в v3): клетки += provokesAo/aoRisk, оружие += isAction/isBonus/isReaction.
#      Значит headW["cells"]/headW["weapons"] растут хвостовыми колонками -> тот же copy+pad.
#   3) Блок оружия ВНУТРИ global-state остаём СТАРОЙ ширины (spec.WEAPON_FEATURES): активация
#      оружия живёт ТОЛЬКО в head оружия, иначе сдвинулся бы grid и разрушился побитовый перенос.
#
# v2 (spec) и v3 (spec3) не тронуты: v4 — отдельная схема с отдельными артефактами. bump схемы
# обязателен, т.к. меняются dims (state/cell_feat/weapon_feat) -> net.load/_guard_compat/ES-сид
# ОТКАЗЫВАЮТ старые v3-веса явно; дообучение идёт через partial-transfer (train._transfer_3_to_4).
from typing import Dict

from arent import spec, spec3

SCHEMA = 4

# ЯВНАЯ ВЕРСИЯ ПРИЗНАКОВ v4 (своя нумерация: head + resource-хвост). dims4() попадает в чекпойнт,
# поэтому _check_feature_compat и датасет-гейт сверяют cell_feat/weapon_feat/state/feat_version.
FEATURES_VERSION = 1

# Голова move-plan = v3 (CELL3_FEATURES, порядок/семантика) + 2 признака атаки по возможности
# в КОНЕЦ слота. provokesAo: Leaves-ли этот план зону живого врага с реакцией (получим Ao);
# aoRisk: нормированный ожидаемый урон от такого провоцируемого Ao.
CELL4_FEATURES: tuple = spec3.CELL3_FEATURES + ("provokesAo", "aoRisk")

# Ширина head оружия = v2-оружие + 3 флага активации в конец слота (isAction/isBonus/isReaction;
# isReaction == может ли оружие нанести Ao, т.е. ближний бой). Влияет ТОЛЬКО на head оружия.
WEAPON_FEATURES4: tuple = spec.WEAPON_FEATURES + ("isAction", "isBonus", "isReaction")

# Хвост state: сколько ресурсов хода осталось у актёра (0/1). Добавляется ПОСЛЕ grid.
RESOURCE_FEATURES: tuple = ("actionRemaining", "bonusRemaining", "reactionRemaining")

# Всё остальное (глубины/слоты/патч) — как в v3 (move-plan голова, то же число слотов).
K_MOVEPLAN = spec3.K_MOVEPLAN
K_TARGETS = spec3.K_TARGETS
K_ALLIES = spec3.K_ALLIES
K_WEAPONS = spec3.K_WEAPONS
PATCH_R = spec3.PATCH_R
PATCH_SIZE = spec3.PATCH_SIZE
NONE_SLOT = spec3.NONE_SLOT


def dims4() -> Dict[str, int]:
    """Размерности v4: как v3, но state += RESOURCE_FEATURES, cell_feat += 2, weapon_feat += 3.

    База state = spec.dims()["state"] (me|enemies|allies|weapons@v2-ширина|grid) — без сдвигов,
    сверх неё только хвост ресурсов. cell_feat/weapon_feat задают ширину Siamese-head.
    """
    d = dict(spec.dims())
    d["schema"] = SCHEMA
    d["cells"] = K_MOVEPLAN + 1
    d["cell_feat"] = len(CELL4_FEATURES)
    d["target_feat"] = len(spec.ENEMY_FEATURES)
    d["weapon_feat"] = len(WEAPON_FEATURES4)          # ширина head оружия (state-блок не трогает)
    d["grid"] = spec.dims()["grid"]
    d["state"] = spec.dims()["state"] + len(RESOURCE_FEATURES)
    d["feat_version"] = FEATURES_VERSION
    return d
