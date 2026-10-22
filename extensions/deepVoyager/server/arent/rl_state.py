# arent/rl_state.py — возобновление PPO: отдельное состояние training (НЕ формат model.json).
#
# model.json/net.save остаются без оптимизатора и читаются обоими бэкендами (см. net.py).
# Для resume PPO нужен ДРУГОЙ снапшот: моменты Adam, счётчик итераций, ВСЕ источники
# случайности (python random, numpy, torch CPU, CUDA RNG, генератор вариантов) и отпечаток
# родителя --warm. Файл ppo_state.pt — производное, его отсутствие не ломает игру модели.
#
# Границы воспроизводимости: побитовое продолжение гарантировано на CPU; на CUDA атомики
# и nondeterministic-ядра ( cudnn benchmark ) не дают bit-exact, поэтому тест детерминизма
# идёт на CPU, а CUDA resume проверяется только по совпадению весов/счётчика.
import os
from typing import Any, Dict, Optional

import torch

from arent import joint, net, spec

RESUME_FORMAT = 1


def rng_snapshot() -> Dict[str, Any]:
    """Собрать все RNG, реально используемые циклом (guarded: numpy/cuda могут отсутствовать)."""
    import random
    snap: Dict[str, Any] = {"python": random.getstate(), "torch": torch.get_rng_state()}
    try:
        import numpy as np
        snap["numpy"] = np.random.get_state()
    except Exception:                                        # numpy не обязателен
        snap["numpy"] = None
    snap["cuda"] = torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None
    return snap


def rng_restore(snap: Dict[str, Any]) -> None:
    """Вернуть RNG: то, чего нет в snapshot (например, CUDA на CPU-машине), молча пропускаем."""
    import random
    if snap.get("python") is not None:
        random.setstate(snap["python"])
    if snap.get("torch") is not None:
        torch.set_rng_state(snap["torch"])
    if snap.get("numpy") is not None:
        try:
            import numpy as np
            np.random.set_state(snap["numpy"])
        except Exception:
            pass
    if snap.get("cuda") is not None and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(snap["cuda"])


def save(path: str, policy: Any, rcfg: Any, net_cfg: net.Config, iteration: int,
         warm_sha: Optional[str], scenario_rng: Any = None) -> str:
    """Записать ppo_state.pt: оптимизатор + итерация + RNG + конфиг + отпечаток родителя.

    scenario_rng — состояние ЛОКАЛЬНОГО random.Random, которым collect перемешивает сцены
    (отдельно от глобального python-RNG): иначе resume продолжил бы другой порядок сцен.
    """
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    rng = rng_snapshot()
    rng["scenario_rng"] = scenario_rng
    payload = {"resume_format": RESUME_FORMAT, "schema": spec.SCHEMA, "dims": spec.dims(),
               "policy_semantics": joint.POLICY_SEMANTICS,
               "net": {"hidden": net_cfg.hidden, "head": net_cfg.head, "seed": net_cfg.seed},
               "rl": rcfg.to_dict() if hasattr(rcfg, "to_dict") else dict(rcfg),
               "iteration": int(iteration), "warm_sha": warm_sha,
               "optim": policy.optim.state_dict(), "params": policy.params, "rng": rng}
    torch.save(payload, path)
    return path


def _guard(state: Dict[str, Any], net_cfg: net.Config, path: str) -> None:
    """Не грузить resume от другой архитектуры/схемы: иначе оптимизатор ляжет на иные слои."""
    if int(state.get("resume_format", 0)) != RESUME_FORMAT:
        raise ValueError(f"resume-файл {path}: формат {state.get('resume_format')!r} не {RESUME_FORMAT}")
    if int(state.get("schema", 0)) != spec.SCHEMA:
        raise ValueError(f"resume-файл {path}: схема {state.get('schema')}, ждём {spec.SCHEMA}")
    if state.get("dims") != spec.dims():
        raise ValueError(f"resume-файл {path}: dims не совпадают с текущей сетью")
    saved = state.get("net") or {}
    if (saved.get("hidden"), saved.get("head")) != (net_cfg.hidden, net_cfg.head):
        raise ValueError(f"resume-файл {path}: hidden/head {saved.get('hidden')}/{saved.get('head')} "
                         f"не {net_cfg.hidden}/{net_cfg.head}")
    # Семантика распределения политики: старый ppo_state калиброван под прежний закон logπ.
    # Моменты Adam и счётчики — не побитово продолжимы поверх нового градиента; веса остаются
    # совместимой тёплой инициализацией (net.load / --warm), но авто-resume оптимизатора запрещён.
    got_sem = int(state.get("policy_semantics", 1))
    if got_sem != joint.POLICY_SEMANTICS:
        raise ValueError(f"resume-файл {path}: семантика политики {got_sem}, ждём "
                         f"{joint.POLICY_SEMANTICS}. Побитовое продолжение PPO поверх оптимизатора "
                         "другой семантики невозможно; используйте эти веса как тёплую "
                         "инициализацию (--warm), оптимизатор начните заново.")


def load(path: str, policy: Any, net_cfg: net.Config) -> Dict[str, Any]:
    """Восстановить оптимизатор/веса в policy; вернуть {iteration, rng, warm_sha, rl}."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"resume-файла нет: {path}")
    state = torch.load(path, map_location=str(getattr(policy, "device", "cpu")),
                       weights_only=False)          # доверяем своему ppo_state.pt (RNG/Adam — pickle)
    _guard(state, net_cfg, path)
    policy.optim.load_state_dict(state["optim"])
    policy.set_params(state["params"])
    return {"iteration": int(state.get("iteration", 0)), "rng": state.get("rng"),
            "warm_sha": state.get("warm_sha"), "rl": state.get("rl")}
