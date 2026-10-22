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
KNOWN_SCHEMAS = (2, 3)      # 2 = клетка-действие, 3 = move-plan (атака+финиш в бюджете хода)


def _profile(schema: Optional[int] = None) -> Dict[str, Any]:
    """Таблица схемы: dims/признаки голов/ключ метки клеток для активной версии задачи.

    Значение по умолчанию = SCHEMA (схема 2), поэтому все прежние вызовы работают ровно как
    раньше. Схема 3 меняет только голову клеток (move-plan: ширина признаков и ключ метки
    plan); состояние/цели/оружие общие со схемой 2.
    """
    s = SCHEMA if schema is None else int(schema)
    if s == 3:
        from arent import spec3
        return {"dims": spec3.dims3(),
                "feats": {"cells": spec3.CELL3_FEATURES, "targets": spec.ENEMY_FEATURES,
                          "weapons": spec.WEAPON_FEATURES},
                "y_key": {"cells": "plan", "targets": "target", "weapons": "weapon"}}
    return {"dims": spec.dims(),
            "feats": {"cells": spec.CELL_FEATURES, "targets": spec.ENEMY_FEATURES,
                      "weapons": spec.WEAPON_FEATURES},
            "y_key": dict(Y_KEY)}


def dims_for(schema: Optional[int] = None) -> Dict[str, int]:
    return _profile(schema)["dims"]


def y_key(schema: Optional[int] = None) -> Dict[str, str]:
    return _profile(schema)["y_key"]


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
    schema: int = 2           # версия задачи: 2 = клетка-действие, 3 = move-plan (см. spec3)

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


def group_total(group: str, schema: Optional[int] = None) -> int:
    return dims_for(schema)[group]


def slot_size(group: str, schema: Optional[int] = None) -> int:
    return len(_profile(schema)["feats"][group])


def label_index(y: Optional[int], total: int) -> int:
    """-1 («не атаковать», «не стрелять») — это последний слот группы, а не отсутствующий."""
    if y is None or y < 0:
        return total - 1
    return min(int(y), total - 1)


def y_index(sample: Dict[str, Any], group: str, schema: Optional[int] = None) -> int:
    """Индекс правильного слота в группе по разметке примера (ключ метки — по схеме)."""
    y = (sample.get("y") or {}).get(y_key(schema)[group])
    return label_index(y, group_total(group, schema))


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
    d = dims or dims_for(getattr(cfg, "schema", SCHEMA))
    schema = d.get("schema", getattr(cfg, "schema", SCHEMA))
    rng = random.Random(cfg.seed)
    head_w, head_b, head_u, head_ub = {}, {}, {}, {}
    for group in GROUPS:
        cols = cfg.head + slot_size(group, schema)
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
    d = dims or dims_for(getattr(cfg, "schema", SCHEMA))
    schema = d.get("schema", getattr(cfg, "schema", SCHEMA))
    total = cfg.hidden * (d["state"] + 1) + cfg.head * (cfg.hidden + 1) + cfg.head + 1
    for group in GROUPS:
        total += cfg.head * (cfg.head + slot_size(group, schema) + 1) + cfg.head + 1
    return total


def save(model: Any, path: str, metrics: Dict[str, Any] = None) -> str:
    """Чекпойнт модели: конфиг + параметры + метрики текущего состояния весов."""
    return save_params(model.params, model.cfg, getattr(model, "name", "pure"), path, metrics,
                       dims=getattr(model, "dims", None))


def save_params(params: Dict[str, Any], cfg: "Config", backend_name: str, path: str,
                metrics: Dict[str, Any] = None, dims: Dict[str, int] = None) -> str:
    """Чекпойнт из готового словаря весов: так пишутся лучшая и последняя эпохи.

    Файл читаемый человеком, без bloat: только веса, размеры и то, чем они измерены.
    """
    schema = getattr(cfg, "schema", SCHEMA)
    checkpoint = {"format": FORMAT, "schema": schema, "dims": dims or dims_for(schema),
                  "backend": backend_name, "config": cfg.to_dict(), "params": params,
                  "metrics": metrics or {}}
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, separators=(",", ":"))
    return path


def feature_version(schema: Optional[int] = None) -> int:
    """Текущая версия ПРИЗНАКОВ активной схемы (ЭТАП 6, часть 1.2).

    Номер схемы (SCHEMA) задаёт семантику действия, версия признаков — состав/ширину
    головы клеток. Для v3 убран slotIndex (22->21) при неизменной SCHEMA=3, поэтому
    признаки версируются отдельно: v2-признаки = 1, v3 permutation-invariant = 2.
    """
    s = SCHEMA if schema is None else int(schema)
    if s == 3:
        from arent import spec3
        return spec3.FEATURES_VERSION
    return 1


def _check_feature_compat(checkpoint: Dict[str, Any], where: str) -> None:
    """Возражаем против чекпойнта v3 со СТАРЫМИ признаками (cell_feat=22 / feat_version!=2).

    Только для схемы 3 (v2 не тронут, прежнее поведение бит-в-бит). Новая permutation-invariant
    голова имеет dims.feat_version==2 и cell_feat==21; старая (до ЭТАПА 5) — cell_feat==22 и
    вовсе без feat_version. Такие веса молча давали бы мусор, поэтому отвергаем явно."""
    if int(checkpoint.get("schema", 0)) != 3:
        return
    from arent import spec3
    dims = checkpoint.get("dims") or {}
    want = spec3.dims3()
    got_feat = dims.get("cell_feat")
    got_ver = dims.get("feat_version")
    if got_feat is None and got_ver is None:
        raise ValueError(
            f"{where}: чекпойнт схемы 3 без отметки версии признаков (dims.cell_feat/"
            f"feat_version) — это формат до ЭТАПА 5; конвейер ждёт feat_version="
            f"{spec3.FEATURES_VERSION} (cell_feat={want['cell_feat']}). Пересоберите выборку/веса.")
    if got_ver != spec3.FEATURES_VERSION or got_feat != want["cell_feat"]:
        raise ValueError(
            f"{where}: признаки v3 несовместимы — в чекпойнте cell_feat={got_feat}/"
            f"feat_version={got_ver}, сейчас cell_feat={want['cell_feat']}/"
            f"feat_version={spec3.FEATURES_VERSION} (ЭТАП 5 убрал slotIndex: 22->21). "
            f"Старые v3-модели ({spec3.CELL_FEAT_V1} признаков) не загружаются новым конвейером.")


def load(path: str, expect_schema: Optional[int] = None) -> Dict[str, Any]:
    """Чекпойнт -> dict; несовместимую схему молча не читаем (иначе сеть предсказывает мусор).

    Без expect_schema принимаем любую ИЗВЕСТНУЮ схему (файл сам описывает свою: конфиг и dims
    дают сети нужную форму). expect_schema задан — требуем ровно её (тёплый старт/совместимость).
    """
    with open(path, encoding="utf-8") as f:
        checkpoint = json.load(f)
    if int(checkpoint.get("format", 0)) != FORMAT:
        raise ValueError(f"Неизвестный формат чекпойнта: {checkpoint.get('format')!r}")
    got = int(checkpoint.get("schema", 0))
    if expect_schema is not None:
        if got != int(expect_schema):
            raise ValueError(f"Чекпойнт схемы {got}, а ждём {int(expect_schema)}: "
                             "нужна новая выборка (spec.SCHEMA менялся)")
    elif got not in KNOWN_SCHEMAS:
        raise ValueError(f"Неизвестная схема чекпойнта {got}: известны {KNOWN_SCHEMAS} "
                         "(spec.SCHEMA меняется)")
    _check_feature_compat(checkpoint, f"Чекпойнт {path}")
    return checkpoint
