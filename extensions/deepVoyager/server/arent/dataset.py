# arent/dataset.py — выборка: состояния -> наблюдение -> векторы + разметка учителя.
#
# Источники состояний: символьные арены playground (5 сцен с проверенным поведением) и
# живые снимки сцены в arent/data/payloads (их кладёт temp/js_arena.js через CDP). И то,
# и другое проходит один конвейер: states.variants -> Teacher.label -> encode.
# Формат хранения — .jsonl (одна строка = один пример): читается потоком, дописывается
# без перезаписи, diff в git остаётся читаемым.
import glob
import hashlib
import json
import os
import random
import zlib
from typing import Any, Dict, Iterator, List, Optional, Tuple

from arent import encode, paths, provenance, slots as slots_mod, spec
from arent.observe import observe
from arent.states import variants
from arent.teacher import pinned
from arent.teachers import DEFAULT_TEACHER, TeacherPolicy, get_teacher
from planner.context import BattleContext
from planner.sim import Simulation


def payload_of(record: Dict[str, Any]) -> Dict[str, Any]:
    """Снимок он же и запрос /plan: файл capture обёрнут, файлы js_arena.js — нет."""
    payload = record.get("payload") if isinstance(record, dict) else None
    return payload if isinstance(payload, dict) else record


def payload_files() -> List[Tuple[str, Dict[str, Any]]]:
    """Живые снимки сцен: data/payloads/*.json и снятые с /plan data/payloads/captures/*."""
    out = []
    patterns = [os.path.join(paths.payload_dir(), "*.json"),
                os.path.join(paths.capture_dir(), "*.json")]
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            with open(path, encoding="utf-8") as f:
                out.append((os.path.splitext(os.path.basename(path))[0], payload_of(json.load(f))))
    return out


def arena_names(want: Optional[List[str]] = None) -> List[str]:
    """Имена арен playground; без want — все, что лежат в playground/arenas."""
    from playground import arena
    names = arena.list_arenas()
    return [n for n in names if not want or n in want]


# Зарезервированный независимый набор (пункт 1 консультанта): арены с этими префиксами
# Никогда не попадают ни в генерацию BC-выборки, ни в PPO train/val/reward/отбор
# чекпойнта — они существуют ТОЛЬКО для финальной оценки bc_v2/bc2 и PPO на одинаковых,
# физически отделённых сценариях. ho_ — прежний замороженный holdout (одиночный герой),
# ho2_ — новый командный holdout v2 (1..6 на 1..6, у каждого токена явная инициатива).
# Префиксы вместо списка-константы: арена добавляется одним файлом, а резерв держится
# centrally (cap_* свежих снимков тем же механизмом).
INDEPENDENT_PREFIXES = ("ho_", "ho2_")
INDEPENDENT_PREFIX = INDEPENDENT_PREFIXES[0]      # обратная совместимость старых ссылок


def is_independent(name: str) -> bool:
    """Имя принадлежит зарезервированному независимому (holdout) набору ho_/ho2_?"""
    return str(name).startswith(INDEPENDENT_PREFIXES)


def scenario_sources(count: int, seed: int
                     ) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Dict[str, Any]]]:
    """F-A: независимые КОМАНДные сцены из генератора scenarios.generate.

    Возвращает (pool, manifest): pool — [(name, payload)] для обучающей разметки/PPO, где
    каждая сцена уже бой 1..6 на 1..6 (своих актёров больше одного, в отличие от 15 рукописных
    арен «герой против N»); manifest — params каждой сцены (seed/архетип/состав/роли), чтобы
    зафиксировать происхождение. Имена gen_* не зарезервированы, поэтому ho_/ho2_ сюда не
    попадают по построению; валидность (есть кого бить, лидер жив, есть оружие) проверяем
    ровно как abset.build_set, но НЕ пишем арены на диск — обучение ест пул напрямую.
    """
    from playground import arena
    from arent import scenarios
    pool: List[Tuple[str, Dict[str, Any]]] = []
    manifest: List[Dict[str, Any]] = []
    for name, raw, params in scenarios.generate(count, seed):
        if is_independent(name):
            continue
        payload = arena.build_payload(raw, name)
        ctx = BattleContext.from_payload(payload)
        if not ctx.hostile_targets() or not ctx.src.is_alive or not payload.get("weapons"):
            continue
        pool.append((name, payload))
        manifest.append(dict(params, group_id=params.get("group_id") or name))
    return pool, manifest


def sources(want_arenas: Optional[List[str]] = None, use_live: bool = True,
            exclude_independent: bool = False, scenario_pool: Optional[List] = None,
            include_arenas: bool = True) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """(имя, payload) по всем источникам состояний: сценарии + арены + живые снимки.

    exclude_independent=True убирает зарезервированный набор (ho_*) — так обучению
    (gen/rl) не достаются сцены, зарезервированные под честную оценку bc2↔PPO.
    scenario_pool — независимые командные сцены F-A; отдаём их ПЕРВЫМИ, чтобы при ограничении
    --count тренировочная выборка состояла из боёв с союзниками, а не из старых 1-на-N арен.
    include_arenas=False — пропустить рукописные арены (режим «только сгенерированные сцены»)."""
    from playground import arena
    if scenario_pool:
        for item in scenario_pool:
            name, payload = item[0], item[1]
            if exclude_independent and is_independent(name):
                continue
            yield name, payload
    if include_arenas:
        for name in arena_names(want_arenas):
            if exclude_independent and is_independent(name):
                continue
            yield name, arena.load_arena(name)
    if use_live:
        for name, payload in payload_files():
            if exclude_independent and is_independent(name):
                continue
            yield name, payload


def independent_sources(want_arenas: Optional[List[str]] = None, use_live: bool = True
                        ) -> List[Tuple[str, Dict[str, Any]]]:
    """Ровно зарезервированный независимый набор — тот же для bc2 и для PPO."""
    return [(n, p) for n, p in sources(want_arenas, use_live) if is_independent(n)]


def sample_one(name: str, payload: Dict[str, Any], teacher: TeacherPolicy, meta: Dict[str, Any],
               initiative: Optional[Tuple[str, ...]] = None
               ) -> Tuple[Optional[Dict[str, Any]], str]:
    """Одно состояние (один микро-шаг нашего актёра) -> пример; причина пропуска, если не вышло."""
    labeled = teacher.label(payload)
    ctx = labeled.ctx
    if not ctx.weapons or not ctx.hostile_targets():
        return None, "no_attack"
    obs = observe(ctx, initiative, ctx.src_id)
    slots = slots_mod.build(ctx, obs)
    if not slots.cells or not slots.targets:
        return None, "no_slots"
    # клетка учителя может не влезть в K_CELLS — вставляем её с его же маршрутом,
    # иначе декодированный план ушёл бы в другую клетку (учим ровно тому, что делает /plan)
    slots_mod.ensure_cell(slots, ctx.src_cell, slots_mod.final_cell(ctx, labeled.actions),
                          slots_mod.dirs_of(labeled.actions))
    label = slots_mod.label_of(ctx, slots, labeled.actions)
    if label is None:
        return None, "label_out_of_slots"      # клетка учителя не влезла в K_CELLS
    if [a.to_dict() for a in slots_mod.decode(slots, label)] != \
            [a.to_dict() for a in labeled.actions]:
        return None, "roundtrip_mismatch"       # три индекса не собирают план учителя обратно
    sample = encode.encode(ctx, obs, slots, label, value=labeled.value,
                           meta=dict(meta, arena=name, score=labeled.score,
                                     depth=labeled.depth))
    sample["meta"]["actions"] = [a.to_dict() for a in labeled.actions]
    return sample, "ok"


def generate(count: int = 200, seed: int = 7, per_src: int = 4, rounds_max: int = 3,
             teacher_rounds: int = 1, teacher_limit: Optional[float] = 1.0,
             want_arenas: Optional[List[str]] = None, use_live: bool = True,
             shallow_k: Optional[int] = None, top_k: Optional[int] = None,
             teacher: str = DEFAULT_TEACHER, scenario_pool: Optional[List] = None,
             scenario_manifest: Optional[List[Dict[str, Any]]] = None,
             include_arenas: bool = True
             ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Сгенерировать не более count примеров; статистика — почему остальные не вышли.

    teacher — имя политики из реестра (arent.teachers); по умолчанию greedy — прежний
    планировщик, поэтому без явного выбора конвейер размечает ровно как до реестра.
    shallow_k/top_k режут ширину симуляции в playout и в lookahead учителя: без них
    состояние стоит доли секунды, с ними — единицы секунд (замер 0.2 шт/с на 8 токенах).
    """
    rng = random.Random(seed)
    teacher_impl = get_teacher(teacher, rounds=teacher_rounds, time_limit_sec=teacher_limit)
    samples: List[Dict[str, Any]] = []
    stats = {"skip": {}, "sources": {}, "schema": spec.SCHEMA, "seed": seed,
             "teacher": teacher_impl.name, "teacher_rounds": teacher_rounds,
             "shallow_k": shallow_k, "top_k": top_k,
             "count": count, "per_src": per_src, "rounds_max": rounds_max,
             "scenario_pool": len(scenario_pool or []), "include_arenas": include_arenas}
    if scenario_manifest is not None:
        stats["scenarios"] = scenario_manifest      # фиксация id/seed/состава каждой сцены
    with pinned(rounds=teacher_rounds, time_limit_sec=teacher_limit,
                shallow_k=shallow_k, top_k=top_k):
        for name, payload in sources(want_arenas, use_live, exclude_independent=True,
                                     scenario_pool=scenario_pool, include_arenas=include_arenas):
            scene_seed = seed ^ zlib.crc32(name.encode("utf-8"))
            for state_payload, meta in variants(payload, rng, count=per_src,
                                                rounds_max=rounds_max):
                order = Simulation.of(BattleContext.from_payload(state_payload),
                                      env_seed=scene_seed).initiative_order
                sample, reason = sample_one(name, state_payload, teacher_impl, meta, order)
                if sample is None:
                    stats["skip"][reason] = stats["skip"].get(reason, 0) + 1
                    continue
                stats["sources"][name] = stats["sources"].get(name, 0) + 1
                samples.append(sample)
                if len(samples) >= count:
                    stats["groups"] = len({s["meta"].get("arena") for s in samples})
                    return samples, stats
    stats["groups"] = len({s["meta"].get("arena") for s in samples})
    return samples, stats


def samples_file(name: str) -> str:
    """Путь выборки: имя внутри data/samples или абсолютный path на готовый .jsonl."""
    return name if os.path.isabs(name) or name.endswith(".jsonl") \
        else os.path.join(paths.samples_dir(), f"{name}.jsonl")


def latest_samples() -> Optional[str]:
    """Самая свежая выборка в data/samples — чтобы train работал без --dataset."""
    directory = paths.samples_dir()
    if not os.path.isdir(directory):
        return None
    files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(".jsonl")]
    return max(files, key=os.path.getmtime) if files else None


def save(samples: List[Dict[str, Any]], name: str, stats: Dict[str, Any] = None) -> str:
    """Выборка в .jsonl + соседний .meta.json (семя, схемы, причины пропусков)."""
    path = samples_file(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False, separators=(",", ":")) + "\n")
    if stats:
        with open(path + ".meta.json", "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=1, sort_keys=True)
    return path


def load(name: str) -> List[Dict[str, Any]]:
    """Чтение .jsonl по имени выборки или абсолютному пути."""
    path = samples_file(name)
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def state_key(sample: Dict[str, Any]) -> str:
    """Ключ примера: состояние + слоты + разметка. meta и value не в счёт — это то же состояние.

    Нужен, чтобы повторный gen поверх накопленного датасета не размечал вторично тот же
    ход планировщика: разметка живым учителем — самое дорогое место всего конвейера.
    """
    parts = {k: sample.get(k) for k in ("schema", "state", "cells", "targets", "weapons",
                                        "mask", "y")}
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def append(samples: List[Dict[str, Any]], name: str,
           stats: Optional[Dict[str, Any]] = None) -> Tuple[str, int, int]:
    """Дописать новые примеры поверх старых, отбросив повторно размеченные состояния.

    Параметры генерации (stats) сливаются в сайдкар .meta.json: накопленный датасет не
    теряет происхождение, а каждый append виден в gen_log (сколько добавлено, чем размечено).
    """
    path = samples_file(name)
    old = load(path) if os.path.exists(path) else []
    seen = {state_key(sample) for sample in old}
    added: List[Dict[str, Any]] = []
    for sample in samples:
        key = state_key(sample)
        if key in seen:
            continue
        seen.add(key)
        added.append(sample)
    save(old + added, name)
    provenance.merge_stats(path, stats, len(added), len(old) + len(added))
    return path, len(added), len(old) + len(added)


def split(samples: List[Dict[str, Any]], frac: float = 0.85, seed: int = 7
          ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """train/val перемешиванием по семени: валидация не видит хвост той же выборки."""
    order = list(samples)
    random.Random(seed).shuffle(order)
    cut = int(len(order) * frac)
    return order[:cut], order[cut:]
