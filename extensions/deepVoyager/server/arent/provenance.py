# arent/provenance.py — происхождение данных и кода: хеши, git, сайдкар выборки.
#
# Модели без происхождения невозможно воспроизвести: один и тот же summary.json может выйти из
# разного датасета, разного кода и разного seed. Здесь — ровно те якоря, что связывают
# чекпойнт с его данными и кодом: SHA-256 файлов, commit + признак dirty + отпечаток кода,
# и накопительный сайдкар .meta.json, который dataset.append больше не теряет.
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def sha256_file(path: str) -> Optional[str]:
    """SHA-256 файла поблочно; None, если файла нет (пути в тестах бывают виртуальными)."""
    if not path or not os.path.exists(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_obj(obj: Any) -> str:
    """Стабильный хеш JSON-совместимого объекта (ключи сортируются)."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: str, data: Any) -> str:
    """Человекочитаемый JSON с сортировкой ключей; создаёт родительский каталог."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    return path


def sidecar_path(samples_path: str) -> str:
    return samples_path + ".meta.json"


def read_sidecar(samples_path: str) -> Dict[str, Any]:
    """Сайдкар выборки (параметры генерации, источники); {} если его никогда не писали."""
    path = sidecar_path(samples_path)
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except (ValueError, OSError):
        return {}


def merge_stats(samples_path: str, gen_stats: Optional[Dict[str, Any]], added: int,
                total: int) -> Dict[str, Any]:
    """Обновить сайдкар поверх append: не потерять старые источники и параметры генерации.

    dataset.append раньше писал выборку без сайдкара — происхождение накопленного датасета
    терялось. Здесь старые поля сохраняются, sources складываются, добавляется журнал gen_log.
    """
    existing = read_sidecar(samples_path)
    merged: Dict[str, Any] = dict(existing)
    gen = gen_stats or {}
    for key in ("schema", "seed", "teacher_rounds", "shallow_k", "top_k",
                "count", "per_src", "rounds_max"):
        if gen.get(key) is not None:
            merged[key] = gen[key]
    sources = dict(merged.get("sources") or {})
    for name, count in (gen.get("sources") or {}).items():
        sources[name] = sources.get(name, 0) + count
    if sources:
        merged["sources"] = sources
    merged["samples"] = total
    log: List[Dict[str, Any]] = list(merged.get("gen_log") or [])
    log.append({"at": now_utc(), "added": added, "total": total,
                "teacher_rounds": gen.get("teacher_rounds", "unknown"),
                "seed": gen.get("seed", "unknown")})
    merged["gen_log"] = log[-20:]
    merged.setdefault("generated_by", "arennet gen (provenance merged on append)")
    write_json(sidecar_path(samples_path), merged)
    return merged


def git_info(package_dir: str) -> Dict[str, Any]:
    """commit/branch/dirty из git рядом с кодом; при отсутствии git — unknown, не исключение."""
    info = {"commit": None, "branch": None, "dirty": None, "code_sha256": None,
            "root": None, "error": None}
    try:
        root = _git(["rev-parse", "--show-toplevel"], package_dir)
        info["root"] = root or None
        info["commit"] = _git(["rev-parse", "HEAD"], package_dir)
        info["branch"] = _git(["rev-parse", "--abbrev-ref", "HEAD"], package_dir)
        status = _git(["status", "--porcelain"], package_dir)
        if status is None:
            info["error"] = "git недоступен"
            return info
        info["dirty"] = bool(status.strip())
        if info["dirty"]:                              # незакоммиченный код — отпечаток пакета
            info["code_sha256"] = code_fingerprint(package_dir)
    except (OSError, subprocess.SubprocessError) as exc:    # noqa: PERF203
        info["error"] = str(exc)
    return info


def _git(args: List[str], cwd: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                             timeout=5, encoding="utf-8")
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def code_fingerprint(package_dir: str) -> Optional[str]:
    """SHA-256 исходников пакета обучения: опечатывает изменённый код при dirty-дереве.

    Считаем по каталогу пакета (arent/), а не по корню git: репозиторий может лежать
    выше (biyk_ext), а пакет — в depths (extensions/deepVoyager/server/arent).
    """
    if not package_dir or not os.path.isdir(package_dir):
        return None
    digest = hashlib.sha256()
    for name in sorted(os.listdir(package_dir)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(package_dir, name), "rb") as f:
            digest.update(name.encode("utf-8"))
            digest.update(f.read())
    return digest.hexdigest()
