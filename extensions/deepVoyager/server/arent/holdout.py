# arent/holdout.py — авторинг замороженного КОМАНДного holdout v2 (ho2_*).
#
# Зачем отдельный набор: ho_* — одиночный герой (наследуемая оценка), а v2 учится на
# командном бою 1..6 на 1..6 с инициативой. Честная оценка bc_v2↔PPO обязана идти на
# тех же командных конфигурациях, но физически отделённых от обучения. Здесь мы ОДИН раз
# собираем N валидных сцен из фиксированного seed, переименовываем в ho2_*, проставляем
# каждому токену ЯВНУЮ инициативу (1..30 из crc32(имя:id) — стабильно между процессами,
# не через hash()) и пишем в playground/arenas. Дальше файлы неприкосновенны: обучение и
# abset их не видят (dataset.is_independent отсекает ho2_, scenarios.write_arenas их не
# перезапишет). Повторный запуск с тем же seed воспроизводит набор байт-в-байт.
import copy
import json
import os
import zlib
from typing import Any, Dict, List, Optional, Tuple

from arent import scenarios, dataset
from playground import arena

HOLDOUT_PREFIX = "ho2_"
HOLDOUT_SEED = 20261021          # фиксированное семя: набор однажды заморожен
HOLDOUT_COUNT = 12               # размер независимого командного набора


def initiative_for(arena_name: str, token_id: str) -> int:
    """Явная инициатива 1..30, детерминированная из crc32 (не hash: он рандомизирован)."""
    return 1 + (zlib.crc32(f"{arena_name}:{token_id}".encode("utf-8")) % 30)


def stamp_initiative(raw: Dict[str, Any], arena_name: str) -> Dict[str, Any]:
    """Каждому токену арены — своё фиксированное initiative (1..30)."""
    for tok in raw.get("tokens") or []:
        tok["initiative"] = initiative_for(arena_name, str(tok["id"]))
    return raw


def build(count: int = HOLDOUT_COUNT, seed: int = HOLDOUT_SEED
          ) -> List[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """count валидных командных сцен как ho2_*; каждая с явной инициативой у всех токенов."""
    out: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
    for i, (_gen_name, raw, params) in enumerate(scenarios.generate(count, seed)):
        name = f"{HOLDOUT_PREFIX}{params['archetype']}_{i:02d}"
        stamped = stamp_initiative(copy.deepcopy(raw), name)
        payload = arena.build_payload(stamped, name)                 # валидируем разбор
        ctx = scenarios._bc(payload)
        if not ctx.hostile_targets() or not ctx.src.is_alive:
            continue
        assert all(t.get("initiative") for t in stamped["tokens"])   # без инициативы не замораживаем
        out.append((name, stamped, dict(params, group_id=name, arena=name)))
    return out


def write(scenes: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
          out_dir: Optional[str] = None, manifest: Optional[str] = None) -> Dict[str, Any]:
    """Пишет ho2_* арены (это И есть holdout — его можно создавать) + манифест происхождения."""
    directory = out_dir or arena.ARENAS_DIR
    os.makedirs(directory, exist_ok=True)
    names = []
    for name, raw, _params in scenes:
        assert dataset.is_independent(name), f"не holdout-имя: {name}"
        with open(os.path.join(directory, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=1)
        names.append(name)
    if manifest:
        os.makedirs(os.path.dirname(manifest), exist_ok=True)
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump({"prefix": HOLDOUT_PREFIX, "seed": scenes[0][2]["seed"] if scenes else None,
                       "count": len(names), "arenas": names}, f, ensure_ascii=False, indent=1)
    return {"written": len(names), "dir": directory, "names": names, "manifest": manifest}


def author(count: int = HOLDOUT_COUNT, seed: int = HOLDOUT_SEED, out_dir: Optional[str] = None,
           manifest: Optional[str] = None) -> Dict[str, Any]:
    """Собрать и заморозить набор одной командой (CLI `arent holdout`)."""
    return write(build(count, seed), out_dir, manifest)
