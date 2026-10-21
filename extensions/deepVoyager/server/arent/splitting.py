# arent/splitting.py — разделение train/validation по НЕЗАВИСИМЫМ сценариям.
#
# Прежний dataset.split мешал строки целиком: производные одного снимка (variant'ы
# states.variants) разъезжались по обе стороны границы, и val.joint мерил память, а не
# обобщение. Здесь группа = исходный снимок (meta.arena): все его варианты попадают в
# одну часть. Точные дубликаты состояний склеиваются union-find'ом, чтобы не пересекали
# границу даже сквозь разные arena. Без meta.arena пример — одиночная группа + предупреждение
# (честная метка «это не содержательная групповая валидация»), а не молчаливый рандом.
import hashlib
import json
import random
from typing import Any, Dict, List, Tuple

GroupKey = str


class UnsafeSplit(ValueError):
    """Группировать нечего (или метаданных нет) — безопасное разделение невозможно."""


def arena_of(sample: Dict[str, Any]) -> str:
    """Имя независимого сценария: meta.arena; пусто — значит снимок не помечен."""
    return str((sample.get("meta") or {}).get("arena") or "")


def state_signature(sample: Dict[str, Any]) -> str:
    """Отпечаток состояния без разметки/меты: одинаковый у точных дубликатов."""
    parts = [sample.get("schema"), sample.get("state"), sample.get("cells"),
             sample.get("targets"), sample.get("weapons"), sample.get("mask")]
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def group_arenas(samples: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """root-кластер -> отсортированные имена arena (для отчёта о пересечениях)."""
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    arena_of_key: Dict[str, str] = {}
    sig_owner: Dict[str, str] = {}
    for idx, sample in enumerate(samples):
        arena = arena_of(sample)
        key = f"arena:{arena}" if arena else f"row:{idx}"
        find(key)
        arena_of_key[key] = arena or f"row#{idx}"
        sig = state_signature(sample)
        if sig in sig_owner:
            union(sig_owner[sig], key)
        else:
            sig_owner[sig] = key
    roots: Dict[str, List[str]] = {}
    for key in arena_of_key:
        roots.setdefault(find(key), []).append(arena_of_key[key])
    return {r: sorted(set(v)) for r, v in sorted(roots.items())}


def split_grouped(samples: List[Dict[str, Any]], frac: float = 0.85, seed: int = 7,
                  strict: bool = False) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]],
                                                 Dict[str, Any]]:
    """Разделить по сценариям: frac — доля в train; val >= 1 группа, train >= 1 группа.

    Возвращает (train, val, report). report фиксирует размеры и число групп и обязан
    показывать пустые пересечения групп и состояний — иначе разделение небезопасно.
    """
    n = len(samples)
    unlabeled = sum(1 for s in samples if not arena_of(s))
    if n == 0:
        return [], [], _report([], [], 0, 0, 0, [])
    roots = group_arenas(samples)                 # cluster root -> имена сценариев
    # индексы по корням
    parent_idx: Dict[str, List[int]] = {}
    # пересобираем members->root тем же union, что и group_arenas
    _reindex(samples, roots, parent_idx)
    keys = sorted(roots)
    warnings: List[str] = []
    if strict and unlabeled:
        raise UnsafeSplit(f"{unlabeled} примеров без meta.arena: безопасный групповой "
                          "split невозможен — пометьте сценарии (meta.arena).")
    if unlabeled:
        warnings.append(f"{unlabeled} примеров без meta.arena сгруппированы построчно: "
                        "их валидация не подтверждает обобщение по сценариям")
    if len(keys) < 2:
        raise UnsafeSplit(f"независимых групп всего {len(keys)} — содержательную "
                          "валидацию построить нельзя (нужно минимум 2 сценария)")
    order = list(keys)
    random.Random(seed).shuffle(order)
    target = int(n * frac)
    train_keys: List[str] = []
    taken = 0
    for root in order[:-1]:                      # последний корень резервируем за val
        if taken < target:
            train_keys.append(root)
            taken += len(parent_idx[root])
    if not train_keys:                           # target==0: хотя бы одна группа в train
        train_keys.append(order[0])
    train_set = set(train_keys)
    train_idx = sorted(i for r in train_keys for i in parent_idx[r])
    val_idx = sorted(i for r in keys if r not in train_set for i in parent_idx[r])
    train = [samples[i] for i in train_idx]
    val = [samples[i] for i in val_idx]
    report = _report(train_keys, [r for r in keys if r not in train_set], len(roots),
                     unlabeled, taken, warnings)
    _assert_clean(train, val, report)
    return train, val, report


def _reindex(samples: List[Dict[str, Any]], roots: Dict[str, List[str]],
             into: Dict[str, List[int]]) -> None:
    """Индексы примеров по тому же разбиению, что вернул group_arenas (по имени сценария)."""
    name_to_root = {name: r for r, names in roots.items() for name in names}
    for idx, sample in enumerate(samples):
        arena = arena_of(sample)
        label = arena or f"row#{idx}"
        into.setdefault(name_to_root[label], []).append(idx)


def _report(train_keys, val_keys, groups, unlabeled, train_samples, warnings):
    return {"method": "grouped", "group_field": "meta.arena", "groups_total": groups,
            "train_groups": len(train_keys), "val_groups": len(val_keys),
            "train_samples": train_samples, "val_samples": 0, "unlabeled_rows": unlabeled,
            "group_overlap": [], "exact_state_overlap": [], "warnings": warnings,
            "train_group_keys": sorted(train_keys), "val_group_keys": sorted(val_keys)}


def _assert_clean(train: List[Dict[str, Any]], val: List[Dict[str, Any]],
                  report: Dict[str, Any]) -> None:
    """Самопроверка: ни сценарий, ни точное состояние не пересекают границу."""
    tr_arenas = {arena_of(s) for s in train if arena_of(s)}
    va_arenas = {arena_of(s) for s in val if arena_of(s)}
    report["group_overlap"] = sorted(tr_arenas & va_arenas)
    tr_sig = {state_signature(s) for s in train}
    va_sig = {state_signature(s) for s in val}
    report["exact_state_overlap"] = sorted(tr_sig & va_sig)
    report["train_samples"] = len(train)
    report["val_samples"] = len(val)


def split_source_names(names: List[str], holdout_frac: float = 0.3,
                       val_frac: float = 0.2, seed: int = 7) -> Tuple[List[str], List[str], List[str]]:
    """Разделить ИМЕНА сценариев на train/val/holdout по группам (имя = независимая группа).

    Тот же детерминизм по seed использует и rl (обучение), и evaluate (отчёт) — значит
    holdout-множество одинаково для bc2 и ppo. Ни одно имя не попадает в две части.
    holdout режется первым и NEVER не используется для rollout/награды/отбора чекпойнта.
    """
    uniq = sorted(set(str(n) for n in names))
    order = list(uniq)
    random.Random(seed).shuffle(order)
    n = len(order)
    n_hold = int(round(n * max(0.0, min(0.9, holdout_frac))))
    n_val = int(round((n - n_hold) * max(0.0, min(0.9, val_frac))))
    holdout = order[:n_hold]
    val = order[n_hold:n_hold + n_val]
    train = order[n_hold + n_val:]
    if not train:                                   # крохотный пул: хотя бы одна группа в train
        train, val = (val + train)[:1], val + train[1:]
        if not train:
            train, val, holdout = val, [], holdout
    return train, val, holdout
