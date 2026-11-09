# arent/encode_v5.py — наблюдение схемы 5: v4 + голова манёвров.
#
# State, cells, targets, weapons — побитово те же, что encode_v4 (перенос весов v4->v5 = copy
# trunk + 3 head без изменений; новая maneuver-голова — cold start). Группа maneuvers добавляется
# как 4-й набор слотов: 3 реальных слота (dash/disengage/dodge) + NONE.
#
# legal-маска для v5 = 4D (joint.legal_mask_v5). Пример содержит ключ y["maneuver"].
from typing import Any, Dict, List

from planner.context import BattleContext
from arent import encode as enc
from arent import encode_v4 as enc4
from arent import joint, spec, spec3, spec4, spec5, slots_v3


_r = enc._r


def maneuver_slot(index: int, total: int, maneuver_data: Dict[str, Any] = None,
                  action_available: bool = True) -> List[float]:
    """Вектор одного слота maneuver-головы (порядок = spec5.MANEUVER_FEATURES, длина 5).

    maneuver_data: {'kind': 'dash'|'disengage'|'dodge', 'id': ...} или None для padding/NONE.
    """
    if not maneuver_data:
        # padding или NONE-слот: slotActive=0, kind-флаги 0
        return enc._empty(len(spec5.MANEUVER_FEATURES), index, total)
    kind = maneuver_data.get("kind", "")
    return [
        1.0,                                        # slotActive
        1.0 if kind == "dash" else 0.0,            # isDash
        1.0 if kind == "disengage" else 0.0,       # isDisengage
        1.0 if kind == "dodge" else 0.0,           # isDodge
        1.0 if action_available else 0.0,          # actionAvailable
    ]


def maneuver_vectors(obs: Dict[str, Any], slots: slots_v3.SlotsV3) -> List[List[float]]:
    """Слоты maneuver head фикс. ширины MANEUVER_FEATURES + NONE последним.

    Всего слотов = spec5.K_MANEUVERS + 1 = 4. Реальные данные манёвров берутся из
    slots.maneuvers (dash=0, disengage=1, dodge=2), NONE-слот = padding (slotActive=1).
    """
    total = spec5.K_MANEUVERS + 1
    me = obs.get("me", {})
    action_avail = float(me.get("actionRemaining", 1.0)) >= 1.0
    vecs: List[List[float]] = []
    for i, m in enumerate(slots.maneuvers[:spec5.K_MANEUVERS]):
        vecs.append(maneuver_slot(i, total, m, action_avail))
    # NONE-слот (последний): always active (выбор «без манёвра» всегда допустим)
    vecs.append(maneuver_slot(total - 1, total, None, True))
    # если манёвров меньше K_MANEUVERS, pad intermediate slots
    while len(vecs) < total:
        vecs.insert(len(vecs) - 1, enc._empty(len(spec5.MANEUVER_FEATURES), len(vecs), total))
    return vecs


def observation(ctx: BattleContext, obs: Dict[str, Any], slots: slots_v3.SlotsV3) -> Dict[str, Any]:
    """Векторы v5 = v4 + maneuvers group/mask."""
    base = enc4.observation(ctx, obs, slots)
    base["schema"] = spec5.SCHEMA
    base["maneuvers"] = maneuver_vectors(obs, slots)
    base["mask"]["maneuvers"] = enc._mask(
        min(len(slots.maneuvers), spec5.K_MANEUVERS) + 1,  # +1 for NONE always masked-in
        spec5.K_MANEUVERS + 1, True)
    return base


def encode(ctx: BattleContext, obs: Dict[str, Any], slots: slots_v3.SlotsV3,
           label: Dict[str, int], value: float = 0.0,
           meta: Dict[str, Any] = None) -> Dict[str, Any]:
    """Один пример выборки схемы 5: v4 + maneuver head + 4D legal."""
    sample = observation(ctx, obs, slots)
    sample["feat_version"] = spec5.FEATURES_VERSION
    sample["legal"] = joint.legal_mask_v5(slots, ctx, spec5.SCHEMA,
                                          action_available=_has_action(obs))
    sample["y"] = {"plan": label["plan"], "target": label["target"],
                   "weapon": label["weapon"], "maneuver": label.get("maneuver", spec5.MANEUVER_NONE)}
    sample["value"] = _r(max(-3.0, min(3.0, value / spec.VALUE_SCALE)))
    sample["meta"] = dict(meta or {}, schema=spec5.SCHEMA, src=ctx.src_id, cell=list(ctx.src_cell))
    return sample


def _has_action(obs: Dict[str, Any]) -> bool:
    """Есть ли у актёра действие (actionRemaining >= 1)."""
    me = obs.get("me", {})
    return float(me.get("actionRemaining", 1.0)) >= 1.0
