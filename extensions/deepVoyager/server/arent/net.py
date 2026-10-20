# arent/net.py — конфигурация сети, форма параметров и формат чекпойнта.
#
# Сеть факторизованная: ствол по состоянию + по голове на каждую группу слотов
# (куда / в кого / чем) + голова стоимости линии. Такой же разрез у жадного
# планировщика, поэтому ответ сети всегда декодируется в корректный список действий,
# и разметка учителя гарантированно лежит внутри пространства модели.
#
# Здесь нет ни тензоров, ни градиентов — только размеры, инициализация и JSON-формат:
# он один для pure-python и для torch, поэтому обученная на 4060 модель читается там,
# где torch не установлен.
import json
import math
import os
import random
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, List, Optional

from arent import paths, spec

FORMAT = 1
SCHEMA = spec.SCHEMA
GROUPS = ("cells", "targets", "weapons")           # как в примере выборки
Y_KEY = {"cells": "cell", "targets": "target", "weapons": "weapon"}
CONFIG_SECTIONS = ("net", "train", "backend")


@dataclass
class Config:
    """Что учим и как: размеры сети (net), оптимизация (train), выбор бэкенда."""
    hidden: int = 96          # ствол: состояние -> hidden
    head: int = 24            # общий слой слотов и ширина головы оценки
    seed: int = 7
    epochs: int = 40
    lr: float = 0.03
    batch: int = 32
    value_w: float = 0.5      # вес головы стоимости в общей потере
    weight_decay: float = 1e-4
    momentum: float = 0.9
    val_frac: float = 0.85
    kind: str = "auto"        # auto | torch | pure
    device: str = "auto"      # auto | cuda | cpu

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


def raw_config() -> Dict[str, Any]:
    """Весь arent/config.json (секции net/train/backend/gen), {} если файла нет."""
    path = paths.config_file()
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f) or {}


def default_config() -> Config:
    """Конфиг из config.json; неизвестные ключи (gen) игнорируются, секции сливаются."""
    data = raw_config()
    flat: Dict[str, Any] = {}
    for section in CONFIG_SECTIONS:
        flat.update(data.get(section) or {})
    return Config.from_dict(flat)


def gen_defaults() -> Dict[str, Any]:
    """Параметры генерации выборки по умолчанию (секция gen того же файла)."""
    return dict(raw_config().get("gen") or {})


def group_total(group: str) -> int:
    return spec.dims()[group]


def slot_size(group: str) -> int:
    feats = {"cells": spec.CELL_FEATURES, "targets": spec.ENEMY_FEATURES,
             "weapons": spec.WEAPON_FEATURES}
    return len(feats[group])


def label_index(y: Optional[int], total: int) -> int:
    """-1 («не атаковать», «не стрелять») — это последний слот группы, а не отсутствующий."""
    if y is None or y < 0:
        return total - 1
    return min(int(y), total - 1)


def y_index(sample: Dict[str, Any], group: str) -> int:
    """Индекс правильного слота в группе по разметке примера."""
    y = (sample.get("y") or {}).get(Y_KEY[group])
    return label_index(y, group_total(group))


def masked_argmax(logits: List[float], mask: List[int]) -> int:
    """Лучший разрешённый слот; -1, если разрешённых нет (тогда действия не будет)."""
    best, value = -1, 0.0
    for i, logit in enumerate(logits):
        if i < len(mask) and mask[i] and (best < 0 or logit > value):
            best, value = i, logit
    return best


def _matrix(rows: int, cols: int, rng: random.Random) -> List[List[float]]:
    """Инициализация Glorot-uniform: без неё первый же relu всё залипает в нули."""
    limit = math.sqrt(6.0 / max(1, rows + cols))
    return [[round(rng.uniform(-limit, limit), 6) for _ in range(cols)] for _ in range(rows)]


def init_params(cfg: Config, dims: Dict[str, int] = None) -> Dict[str, Any]:
    """Слой-в-слой словарь списков: тот же формат у pure-python и у torch.

    Ключи: trunk1/b1 (состояние -> hidden), trunk2/b2 (hidden -> head),
    headW/headB/headU/headUB по группам слотов, valueW/valueB — оценка линии.
    """
    d = dims or spec.dims()
    rng = random.Random(cfg.seed)
    head_w, head_b, head_u, head_ub = {}, {}, {}, {}
    for group in GROUPS:
        cols = cfg.head + slot_size(group)
        head_w[group] = _matrix(cfg.head, cols, rng)
        head_b[group] = [0.0] * cfg.head
        head_u[group] = [round(rng.uniform(-0.1, 0.1), 6) for _ in range(cfg.head)]
        head_ub[group] = 0.0
    return {
        "trunk1": _matrix(cfg.hidden, d["state"], rng), "b1": [0.0] * cfg.hidden,
        "trunk2": _matrix(cfg.head, cfg.hidden, rng), "b2": [0.0] * cfg.head,
        "headW": head_w, "headB": head_b, "headU": head_u, "headUB": head_ub,
        "valueW": [round(rng.uniform(-0.1, 0.1), 6) for _ in range(cfg.head)],
        "valueB": 0.0,
    }


def param_count(cfg: Config, dims: Dict[str, int] = None) -> int:
    """Сколько весов в модели такой конфигурации (для отчёта; сверяется тестом)."""
    d = dims or spec.dims()
    total = cfg.hidden * (d["state"] + 1) + cfg.head * (cfg.hidden + 1) + cfg.head + 1
    for group in GROUPS:
        total += cfg.head * (cfg.head + slot_size(group) + 1) + cfg.head + 1
    return total


def save(model: Any, path: str, metrics: Dict[str, Any] = None) -> str:
    """Чекпойнт модели: конфиг + параметры + метрики текущего состояния весов."""
    return save_params(model.params, model.cfg, getattr(model, "name", "pure"), path, metrics)


def save_params(params: Dict[str, Any], cfg: "Config", backend_name: str, path: str,
                metrics: Dict[str, Any] = None) -> str:
    """Чекпойнт из готового словаря весов: так пишутся лучшая и последняя эпохи.

    Файл читаемый человеком, без bloat: только веса, размеры и то, чем они измерены.
    """
    checkpoint = {"format": FORMAT, "schema": SCHEMA, "dims": spec.dims(),
                  "backend": backend_name, "config": cfg.to_dict(), "params": params,
                  "metrics": metrics or {}}
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, separators=(",", ":"))
    return path


def load(path: str) -> Dict[str, Any]:
    """Чекпойнт -> dict; несовместимую схему молча не читаем (иначе сеть предсказывает мусор)."""
    with open(path, encoding="utf-8") as f:
        checkpoint = json.load(f)
    if int(checkpoint.get("format", 0)) != FORMAT:
        raise ValueError(f"Неизвестный формат чекпойнта: {checkpoint.get('format')!r}")
    if int(checkpoint.get("schema", 0)) != SCHEMA:
        raise ValueError(f"Чекпойнт схемы {checkpoint.get('schema')}, а ждём {SCHEMA}: "
                         "нужна новая выборка (spec.SCHEMA менялся)")
    return checkpoint
