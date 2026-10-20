# arent/backend.py — кем считать: torch (CUDA на 4060) или чистым python.
#
# Выбор один и там же, где и всё остальное в arent: если torch установлен и есть
# CUDA, учимся на видеокарте; если нет — работает pure-python (медленнее, но модель
# та же). Формат чекпойнта общий, поэтому обученное на одной машине читается другой.
import sys
from typing import Any, Dict, List, Optional

from arent import net, paths
from arent.pure_net import PurePolicy


def torch_ready() -> bool:
    """Импортируется ли torch в этом окружении (без импорта самого пакета на уровне строк)."""
    try:
        import torch            # noqa: F401  проверка наличия, а не использование
        return True
    except Exception:
        return False


def available() -> List[str]:
    return (["torch"] if torch_ready() else []) + ["pure"]


def resolve(kind: str = "auto") -> str:
    """auto -> torch, если он есть; явный torch без torch — ошибка с подсказкой."""
    if kind == "pure":
        return "pure"
    if kind == "torch":
        if not torch_ready():
            raise RuntimeError("torch не установлен: запусти arent/setup.bat "
                               "(он ставит cu121 сборки в arent/.venv)")
        return "torch"
    return "torch" if torch_ready() else "pure"


def build(cfg: Optional[net.Config] = None, kind: str = "auto",
          params: Dict[str, Any] = None, device: Optional[str] = None) -> Any:
    """Политик с нужным бэкендом.

    params — веса из чекпойнта (иначе инициализация по cfg.seed); device=None — из cfg.
    """
    cfg = cfg or net.default_config()
    kind = resolve(kind)
    if kind == "torch":
        from arent.torch_net import TorchPolicy
        return TorchPolicy(cfg, params, device or cfg.device)
    return PurePolicy(cfg, params)


def load_policy(path: str, kind: str = "auto") -> Any:
    """Чекпойнт -> политик. kind=auto: свой бэкенд, если он доступен, иначе pure."""
    checkpoint = net.load(path)
    cfg = net.Config.from_dict(checkpoint.get("config") or {})
    want = checkpoint.get("backend", "pure") if kind == "auto" else kind
    try:
        return build(cfg, kind=want, params=checkpoint["params"])
    except RuntimeError:
        return build(cfg, kind="pure", params=checkpoint["params"])


def describe() -> Dict[str, Any]:
    """Что увидит `arent info`: чем считаем, есть ли CUDA, где данные."""
    cuda, name, version = False, None, None
    if torch_ready():
        import torch
        version = torch.__version__
        cuda = bool(torch.cuda.is_available())
        name = torch.cuda.get_device_name(0) if cuda else None
    cfg = net.default_config()
    return {"kind": resolve(cfg.kind), "torch": version or "не установлен", "cuda": cuda,
            "device": name or "cpu", "python": sys.version.split()[0],
            "available": available(), "workspace": paths.workspace(),
            "config": cfg.to_dict(), "params": net.param_count(cfg)}
