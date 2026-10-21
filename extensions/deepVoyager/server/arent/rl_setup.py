# arent/rl_setup.py — подготовка PPO: warm-start весов, замороженный V_ref (потенциал Φ),
# групповой split сцен train/val/holdout и разнообразие rollout через states.variants.
#
# Отделено от rl.py (цикл/чекпойнты) и rollout.py (данные/GAE): здесь только настройка
# старта. Warm-start берёт из BC ствол и три action-головы, но НЕ переносит калибровку
# критика: BC-критик предсказывает нормированную ценность одного хода учителя (±3), а
# PPO-критик — дисконтированный возврат shaped-награды; перенос был бы смещённым baseline.
# V_ref = тот же BC-чекпойнт целиком (со своим value head), заморожен и служит ТОЛЬКО
# функцией потенциала Phi(s)=V_ref(s) для shaping; он не обучается и читает то же
# наблюдение (encode.observation), что и среда.
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from arent import backend, net, paths, spec, states
from arent.splitting import split_source_names

Source = Tuple[str, Dict[str, Any]]


def resolve_warm_path(warm: str) -> str:
    """runs/<имя>/model_best.json, иначе model.json, иначе явный путь; если нет — ошибка."""
    if warm and os.path.exists(warm):
        return warm
    best = paths.file_in(paths.run_dir(warm), "model_best.json") if warm else None
    if best and os.path.exists(best):
        return best
    path = paths.checkpoint(warm) if warm else None
    if path and os.path.exists(path):
        return path
    raise RuntimeError(f"Чекпойнта нет: {warm} — runs/<имя>/model_best.json или путь")


def _guard_compat(checkpoint: Dict[str, Any], net_cfg: net.Config, path: str) -> None:
    """Не грузим чекпойнт другой архитектуры/схемы: сверяем dims и hidden/head."""
    saved = net.Config.from_dict(checkpoint.get("config") or {})
    if (saved.hidden, saved.head) != (net_cfg.hidden, net_cfg.head):
        raise RuntimeError(f"Чекпойнт {path}: hidden={saved.hidden}/head={saved.head}, "
                           f"просим {net_cfg.hidden}/{net_cfg.head}")
    if checkpoint.get("dims") != spec.dims():
        raise RuntimeError(f"Чекпойнт {path}: dims не совпадают с текущей схемой spec.dims()")


def warm_params(net_cfg: net.Config, warm: str,
                reset_value_head: bool = True) -> Tuple[Dict[str, Any], str]:
    """Весы для старта PPO из BC. reset_value_head=True: ствол+головы из BC, критик заново."""
    path = resolve_warm_path(warm)
    params = dict(net.load(path)["params"])
    _guard_compat(net.load(path), net_cfg, path)
    if reset_value_head:
        fresh = net.init_params(net_cfg)
        params["valueW"] = fresh["valueW"]
        params["valueB"] = fresh["valueB"]
    return params, path


def build_vref(net_cfg: net.Config, warm: str,
               device: Optional[str]) -> Tuple[Any, Callable[[Dict[str, Any]], float]]:
    """Замороженный V_ref из BC-чекпойнта + phi(sample)->float для потенциального shaping."""
    path = resolve_warm_path(warm)
    checkpoint = net.load(path)
    _guard_compat(checkpoint, net_cfg, path)
    policy = backend.build(net_cfg, kind="torch", params=checkpoint["params"], device=device)
    policy.layers.eval()

    def phi(sample: Dict[str, Any]) -> float:
        return float(policy.predict(sample)["value"])
    return policy, phi


def split_scenarios(sources: List[Source], holdout_frac: float, val_frac: float,
                    seed: int) -> Tuple[List[Source], List[Source], List[Source]]:
    """(name,payload) -> train/val/holdout по группам-именам; множества непересекающиеся."""
    lookup: Dict[str, Any] = {}
    for name, payload in sources:
        lookup.setdefault(str(name), payload)
    train, val, holdout = split_source_names(list(lookup), holdout_frac, val_frac, seed)
    pick = lambda names: [(n, lookup[n]) for n in names]      # noqa: E731
    return pick(train), pick(val), pick(holdout)


def variant_sources(train: List[Source], seed: int, per_src: int = 3) -> List[Source]:
    """Разнообразие rollout: варианты стартовых состояний TRAIN-сцен (holdout не трогаем).

    states.variants гоняет случайные продолжения боя; имя группы остаётся базовой ареной,
    поэтому расширение пула не смешивает обуч/оценочные сценарии.
    """
    import random
    rng = random.Random(seed ^ 0x5EED)
    out: List[Source] = []
    for name, payload in train:
        out.append((name, payload))                          # исходное состояние всегда в пуле
        for i, (variant, _meta) in enumerate(states.variants(payload, rng, count=per_src)):
            out.append((f"{name}#v{i}", variant))
    return out
