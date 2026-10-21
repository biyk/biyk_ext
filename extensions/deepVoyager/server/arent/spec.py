# arent/spec.py — контракт наблюдения v2 (командный бой) и пространство действий.
#
# Схема v2 добавляет признаки инициативы/акт-фракции/террейна под командный бой, но НЕ
# раздувает патч поля (PATCH_R остаётся 5): вместо +168 grid-признаков — ~26 state-признаков
# по слотам и ME. Изменение состава признака = смена SCHEMA: старые чекпойнты перестают
# соответствовать размерам сети, и load обязан отказаться, а не предсказывать молча.
from typing import Dict, Tuple

SCHEMA = 2

# Сколько слотов отдаём под каждую группу. Сверх лимита берём ближайших по дистанции:
# размер входа не должен расти вместе со сценой, иначе сеть зависела бы от арены.
K_TARGETS = 8            # врагов в наблюдении
K_ALLIES = 6             # союзников
K_WEAPONS = 8            # своё оружие (+1 слот «не атаковать»)
K_CELLS = 48             # клеток хода («остаться» всегда входит в перебор)
PATCH_R = 5              # радиус патча поля в клетках: (2R+1)^2 = 121 признак
PATCH_SIZE = 2 * PATCH_R + 1

NONE_SLOT = -1           # «ни цели», «ни оружия» — голова masked, индекс -1
HIT_CHANCE_MIN = 0.05    # d20: 1 всегда промах, 20 всегда попадание
HIT_CHANCE_MAX = 0.95

# Символы патча поля (те же, что в живом дампе): '.' свободно, '#' стена/край,
# 'E' враг, 'A' союзник, 'T' прочий токен, '@' герой.
GRID_LETTERS = {".": 0.0, "#": 1.0, "E": 2.0, "A": 3.0, "T": 4.0, "@": 5.0}

# Нормировки: делитель = «typical max» признака, чтобы всё ложилось в ±1..±2.
D_SCALE = 12.0           # дистанция и смещения, в клетках
FT_SCALE = 120.0         # дальность стрельбы, в клетках (24 фута = 1 клетка)
HP_SCALE = 40.0          # хп и КД: 40 — потолок типового NPC
DMG_SCALE = 10.0         # ожидание урона за атаку
VALUE_SCALE = 60.0       # значение линии: уверенная атака (30) + штраф урона (-30)

ME_FEATURES: Tuple[str, ...] = (
    "alive", "hp", "hpMax", "hpFrac", "ac", "speedCells", "moveCellsFrac",
    "dmgAvg", "toHit", "reachCells", "rangeCells", "attacks", "bonusAction",
    "enemiesAlive", "alliesAlive", "threatNow", "incomingAvg", "canBeCharged",
    "isolated", "cr",
    # v2 team combat: доля союзников, уже сходивших в раунде + сводка террейна впереди
    # (значения наполняет observe/sim в коммитах №2-№3; до того — 0, форма зафиксирована).
    "alliesActedFraction", "hasLosToNearestEnemy", "pathLenFrac", "wallsInView",
)
ENEMY_FEATURES: Tuple[str, ...] = (
    "slotActive", "slotIndex", "dx", "dy", "dist", "hpFrac", "ac", "speedCells",
    "dmgAvg", "toHit", "reachCells", "rangeCells", "los", "canHitMe", "canReachMe",
    "inMyMelee", "inMyRange", "isTarget", "isDead", "dmgToMe",
    # v2: позиция в порядке инициативы и «ходит следующим» (не вставай на линию огня).
    "initiativeIndex", "isNextToAct",
)
ALLY_FEATURES: Tuple[str, ...] = (
    "slotActive", "slotIndex", "dx", "dy", "dist", "hpFrac", "ac", "speedCells",
    "dmgAvg", "los", "blocksMe", "isMe",
    # v2: индекс инициативы союзника (кого ждать раньше/позже меня).
    "initiativeIndex",
)
WEAPON_FEATURES: Tuple[str, ...] = (
    "slotActive", "slotIndex", "dmgAvg", "toHit", "melee", "sureCells", "doubtCells",
    "reachesAny", "bestModeSure", "ranged", "thrown",
)
CELL_FEATURES: Tuple[str, ...] = (
    "slotActive", "slotIndex", "dx", "dy", "dist", "pathLen", "stay", "free",
    "nearestEnemy", "canAttack", "sureAttack", "doubtAttack", "losAny", "threatCount",
    "incoming", "cover", "aliveFrac", "crowd",
)


def dims() -> Dict[str, int]:
    """Размерности сети: state и три группы слотов (по составу признаков выше)."""
    grid = PATCH_SIZE * PATCH_SIZE
    state = (len(ME_FEATURES) + K_TARGETS * len(ENEMY_FEATURES)
             + K_ALLIES * len(ALLY_FEATURES) + (K_WEAPONS + 1) * len(WEAPON_FEATURES) + grid)
    return {
        "state": state,
        "cells": K_CELLS + 1, "cell_feat": len(CELL_FEATURES),
        "targets": K_TARGETS + 1, "target_feat": len(ENEMY_FEATURES),
        "weapons": K_WEAPONS + 1, "weapon_feat": len(WEAPON_FEATURES),
        "grid": grid,
    }


def hit_chance(to_hit: float, target_ac: float, fallback: float) -> float:
    """Вероятность попадания атаки +to_hit в КД target_ac (d20, криты и промахи по правилам).

    0..неизвестно -> fallback (rules.hitChance): старый клиент КД не присылает,
    и молча считать 0% — значит научить модель бояться всех.
    """
    if not target_ac:
        return float(fallback)
    chance = (21 - (float(target_ac) - float(to_hit or 0))) / 20.0
    return min(HIT_CHANCE_MAX, max(HIT_CHANCE_MIN, chance))
