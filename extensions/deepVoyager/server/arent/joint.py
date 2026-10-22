# arent/joint.py — совместное распределение политики по множеству допустимых троек.
#
# Головы сети (куда/в кого/чем) маскируются НЕЗАВИСИМО и не кодируют совместную
# легальность атаки: оружие должно доставать цель ИЗ позиции атаки выбранной клетки/плана
# по линии видимости. Этап 2 научил СРЕДУ постфактум чинить недопустимую тройку (legalize
# убирает атаку в NONE), но для PPO этого мало: действие, выбранное произведением голов и
# затем «починенное», распределено НЕ по тому закону, логарифм которого подставляется в
# отношение важности. Здесь — честный закон: берём произведение вероятностей голов,
# обнуляем НЕдопустимые тройки и нормируем по множеству совместно допустимых.
#
# Ключевые свойства (это и чинит математику PPO, и оставляет simulate/урон нетронутыми):
#  • каждое выбранное действие уже совместимо, поэтому защитный legalize для него —
#    тождество (ничего не правим, причина правки не появляется);
#  • logπ, энтропия и вероятность исполненного действия берутся ОДНОГО и того же закона —
#    нормированного произведения голов по допустимому множеству (rollout == update);
#  • «не атаковать» представлено РОВНО ОДНИМ вариантом на клетку/план — (поз, цель=NONE,
#    оружие=NONE): не появляется случайное преимущество из-за дублирующих no-attack троек;
#  • единственный источник правды о легальности — slots.attackable / slots_v3.attackable_v3
#    (тот же примитив, что у legalize): здесь он только перечисляет допустимые тройки.
#
# Индексация совпадает с длиной векторов голов: group totals из net.dims_for(schema)
# (клетки/план: +1 NONE-слот недоступен маской; цели/оружие: последний слот = NONE).
from typing import Any, Dict, List

import math

from arent import net, slots as slots_mod, slots_v3, spec, spec3

# «Не атаковать» = последний masked-слот соответствующей группы (совпадает с legalize/env).
NONE_TARGET = spec.K_TARGETS
NONE_WEAPON = spec.K_WEAPONS

# Версия СЕМАНТИКИ распределения политики (не формата файлов и не схемы признаков).
# 1 = «произведение независимых masked-голов», logπ исполненного действия считался без
#     совместной нормировки (rollout == update, но НЕ равен закону «сэмплируй-и-почини»);
# 2 = нормированное произведение голов по множеству совместно допустимых троек (здесь).
# Меняется ТОЛЬКО если меняется сам закон выбора/logπ/энтропии. Это помечает чекпойнты и
# блокирует побитовое продолжение PPO поверх оптимизатора, накопленного по другой семантике
# (моменты Adam и старый буфер logp калиброваны под прежний градиент). Веса при этом остаются
# совместимой тёплой инициализацией (net.load / --warm не трогает этот флаг).
POLICY_SEMANTICS = 2


def _pos_key(schema: int) -> str:
    return "plan" if int(schema) == spec3.SCHEMA else "cell"


def group_totals(schema: int) -> Dict[str, int]:
    """Длины векторов голов (столько же отмеряет сеть): cells/plans, targets, weapons."""
    d = net.dims_for(schema)
    return {"cells": d["cells"], "targets": d["targets"], "weapons": d["weapons"]}


def legal_mask(slots: Any, ctx: Any, schema: int) -> List[List[List[int]]]:
    """3D-булева маска совместно допустимых троек [pos][target][weapon].

    Единица стоит ровно на:
      • каноническом «не атаковать» для каждой реальной позиции — (p, NONE_TARGET, NONE_WEAPON);
      • реальной атаке (p, t, w), где attackable/attackable_v3 вернул True.
    Всё остальное (_pad_, неканонические no-attack вроде (p, t, NONE)) — нули, чтобы
    исключённые варианты не получали вероятности и не плодили дублей действия без атаки.
    """
    totals = group_totals(schema)
    p_n, t_n, w_n = totals["cells"], totals["targets"], totals["weapons"]
    mask = [[[0] * w_n for _ in range(t_n)] for _ in range(p_n)]
    n_pos = len(slots.plans if schema == spec3.SCHEMA else slots.cells)
    targets = slots.targets
    weapons = slots.weapons
    check = (slots_v3.attackable_v3 if schema == spec3.SCHEMA else slots_mod.attackable)
    for p in range(min(n_pos, p_n)):
        mask[p][NONE_TARGET][NONE_WEAPON] = 1        # ровно один вариант «без атаки» на позицию
        for t in range(min(len(targets), t_n)):
            for w in range(min(len(weapons), w_n)):
                if check(slots, ctx, p, t, w):
                    mask[p][t][w] = 1
    return mask


def is_jointly_legal(action: Dict[str, int], mask: List[List[List[int]]], schema: int) -> bool:
    """Leжит ли тройка в допустимом множестве (для проверки, что выбор/decode законны)."""
    key = _pos_key(schema)
    p = int(action.get(key, -1))
    t = int(action.get("target", spec.NONE_SLOT))
    w = int(action.get("weapon", spec.NONE_SLOT))
    try:
        return bool(mask[p][t][w])
    except IndexError:
        return False


def example_id(sample: Dict[str, Any]) -> str:
    """Человекочитаемый идентификатор примера для диагностики (meta.arena/src/cell)."""
    meta = sample.get("meta") or {}
    parts = [str(meta.get("arena", "?")), f"src={meta.get('src', '?')}",
             f"cell={meta.get('cell')}"]
    return "/".join(parts)


def ensure_jointly_legal(sample: Dict[str, Any], schema: int = None):
    """Индексы тройки метки учителя (pos, target, weapon) — или диагностическая ошибка.

    Единая точка правды и для BC-потери, и для проверок: требует, чтобы в примере лежала
    точная совместная маска ``legal`` (= joint.legal_mask, снятая при сборе примера там, где
    живы ctx/slots), и что метка учителя принадлежит A(s). Молча НЕ чиним и НЕ исключаем:
    недопустимая или неканоническая метка (например (pos, цель, NONE-оружие) вместо
    канонического (pos, NONE, NONE)) поднимает ValueError с id примера, схемой и причиной.
    """
    s = int(sample.get("schema", schema if schema is not None else net.SCHEMA))
    legal = sample.get("legal")
    ident = example_id(sample)
    if legal is None:
        raise ValueError(
            f"пример {ident} (schema {s}): нет совместной маски 'legal'. Joint-BC требует "
            "точное A(s) из joint.legal_mask, снятого при генерации примера (ctx жив); "
            "восстановить его из векторов наблюдения по приблизительным признакам нельзя — "
            "перегенерируйте выборку новым форматом (encode.encode теперь пишет 'legal').")
    totals = group_totals(s)
    none_t, none_w = totals["targets"] - 1, totals["weapons"] - 1
    ip = net.y_index(sample, "cells", s)
    it = net.y_index(sample, "targets", s)
    iw = net.y_index(sample, "weapons", s)
    # Канонизация действия «без атаки»: цель, выбранная БЕЗ оружия, — то же самое действие,
    # что ход без цели (симуляция не производит удар). Приводим (поз, цель, NONE) к единственному
    # каноническому (поз, NONE, NONE), чтобы дубль не создавал лишнюю вероятность в A(s). Это
    # проекция факторизованной метки на совместное действие, а не «починка» недопустимой атаки.
    if iw == none_w:
        it = none_t
    try:
        ok = bool(legal[ip][it][iw])
    except IndexError:
        ok = False
    if not ok:
        raw = (sample.get("y") or {})
        raise ValueError(
            f"пример {ident} (schema {s}): метка учителя (pos={ip}, target={it}, weapon={iw}; "
            f"исходная y={raw}) вне допустимого множества A(s) — атака несовместна (цель/оружие "
            "не достают из позиции атаки) либо указана при отсутствии оружия.")
    return ip, it, iw


def argmax(mask: List[List[List[int]]], cell_logp: List[float], target_logp: List[float],
           weapon_logp: List[float], schema: int) -> Dict[str, int]:
    """Детерминированный joint-выбор: лучшая по совместной вероятности DOпустимая тройка.

    Возвращает метку {cell|plan, target, weapon} (ключ позиции — по схеме). Единственная
    математика совместного argmax: serving-декодер (decode) и этап-3 сравнение зовут её,
    дублирования нет. Независимый argmax+legalize остался только как диагностический
    baseline (см. independent_baseline).
    """
    best, score = None, float("-inf")
    for p, lc in enumerate(cell_logp):
        for t, lt in enumerate(target_logp):
            for w, lw in enumerate(weapon_logp):
                if not mask[p][t][w]:
                    continue
                s = lc + lt + lw
                if s > score:
                    score, best = s, (p, t, w)
    if best is None:                                  # маска обязана быть непустой (есть no-attack)
        return {}
    p, t, w = best
    return {_pos_key(schema): p, "target": t, "weapon": w}


def logz(mask: List[List[List[int]]], cell_logp: List[float], target_logp: List[float],
         weapon_logp: List[float]) -> float:
    """Лог-сумма-экспонента по A(s) поверх log-softmax голов: нормировка joint-закона.

    Тот же численный приём (max+log Σ exp), что в pure_net._accumulate и _joint_batch —
    здесь только для отчётности (joint-вероятность выбранной тройки в serving).
    """
    top = float("-inf")
    vals: List[float] = []
    for p, row in enumerate(mask):
        for t, col in enumerate(row):
            for w, ok in enumerate(col):
                if ok:
                    u = cell_logp[p] + target_logp[t] + weapon_logp[w]
                    vals.append(u)
                    if u > top:
                        top = u
    if not vals:
        raise ValueError("пустое A(s): нормировка joint-закона неопределена")
    return top + math.log(sum(math.exp(u - top) for u in vals))


def decode(model: Any, sample: Dict[str, Any], slots: Any = None, ctx: Any = None,
           schema: int = None) -> Dict[str, Any]:
    """Единый детерминированный joint-декодер serving-путей (play/evaluate/team_eval).

    Выбор — максимум СОВМЕСТНОЙ вероятности по A(s): те же masked log-softmax голов
    (model.head_logp) и та же проверка легальности (legal_mask/attackable), что у обучения
    (joint NLL) и у стохастического PPO-выбора (torch_rl.PPOAgent.act). Поэтому предложение
    политики уже совместно, а защитный legalize среды — тождество (Этап 7, часть 1).
    Маска берётся из sample['legal'], если среда её приложила; иначе считается здесь же,
    по тем же slots/ctx. Математика легальности не дублируется.
    """
    s = int(schema if schema is not None else sample.get("schema", net.SCHEMA))
    legal = sample.get("legal")
    if legal is None:
        if slots is None or ctx is None:
            raise ValueError("joint-декодеру нужна маска A(s): sample['legal'] или (slots, ctx)")
        legal = legal_mask(slots, ctx, s)
    lcs, lts, lws, value = model.head_logp(sample)
    label = argmax(legal, lcs, lts, lws, s)
    if not label:
        raise ValueError("joint-декодер вернул пустую метку: маска A(s) пуста — контракт нарушен")
    z = logz(legal, lcs, lts, lws)
    p, t, w = label[_pos_key(s)], label["target"], label["weapon"]
    prob = math.exp(lcs[p] + lts[t] + lws[w] - z)
    return {"label": label, "mask": legal, "value": value,
            "logp": {"cells": lcs, "targets": lts, "weapons": lws},
            "joint_prob": round(prob, 6)}


def independent_baseline(logps: Dict[str, List[float]], schema: int) -> Dict[str, int]:
    """Диагностический baseline: НЕЗАВИСИМЫЙ argmax каждой головы (старый serving до этапа 7).

    Считается из тех же полнодлинных log-softmax, что и joint-выбор: вне маски стоит PAD,
    поэтому head-argmax всегда берёт masked-in слот. Служит лишь для метрики «доля
    независимых предложений вне A(s)» и НЕ является действием политики.
    """
    key = _pos_key(schema)
    out: Dict[str, int] = {}
    for group, name in (("cells", key), ("targets", "target"), ("weapons", "weapon")):
        vec = logps[group]
        out[name] = max(range(len(vec)), key=vec.__getitem__) if vec else spec.NONE_SLOT
    return out
