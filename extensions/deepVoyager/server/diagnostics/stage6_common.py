# diagnostics/stage6_common.py — ЭТАП 6: общий стратифицированный пул сцен + учёт примеров (1.1).
#
# Пул TRAIN-состояний намеренно стратифицирован по двум семействам источников:
#   • генерируемые КОМАНДные сцены (dataset.scenario_sources) — размеры команд 1..6, роли,
#     оружие, дистанции расстановки;
#   • рукописные арены playground (cover/LOS/углы/коридоры/копьё/китинг/два оружия) — укрытия
#     и линии видимости, которых в случайных сценах мало.
# ho*/ho2*/ho3_* арены сюда НЕ входят: dataset.is_independent исключает их из
# gen/rl по построению — они существуют только для независимой оценки (часть 5).
#
# Учёт (1.1) идёт ровно тем же кодом, что производит выборку (dataset.generate -> sample_one_v3),
# поэтому числа сходятся: states = ok + сумма пропусков по причинам; ok делится на атаку/без-атаки
# по факту USE в плане учителя; каждая метка обязана лежать в A(s) (joint.ensure_jointly_legal).
import random
import sys
import zlib
from typing import Any, Dict, List, Tuple

from arent import dataset, joint, paths, spec, spec3
from arent.states import variants
from arent.teachers import get_teacher
from planner.context import BattleContext
from planner.geometry import apply_moves, cell_distance
from planner.sim import Simulation

# рукописные арены с укрытием/LOS/дальним боем (не ho*) — берём только реально существующие
TRAIN_ARENAS = [
    "cover_alley", "corridor_archer", "door_chokepoint", "pillars_three", "ranged_kite",
    "pike_standoff", "javelin_open", "two_weapons", "fork_two_melee", "five_surround",
    "archer_pair", "glass_cannon", "tank_and_adds", "wide_fast", "bruiser_death",
]
# seed ЭТАПА 6 (фиксирован, чтобы учёт/выборка/сплит были воспроизводимы)
SEED = 20261022


def _ensure_server_path() -> None:
    server = paths.source_dir()                       # .../server/arent
    root = server[:-len("arent")] if server.endswith("arent") else server
    if root not in sys.path:
        sys.path.insert(0, root)


def arena_sources(names: List[str]) -> List[Tuple[str, Dict[str, Any]]]:
    """(имя, payload) существующих рукописных арен из playground (только запрошенные имена)."""
    _ensure_server_path()
    from playground import arena
    have = set(arena.list_arenas())
    out = []
    for n in names:
        if n not in have or dataset.is_independent(n):
            continue
        out.append((n, arena.load_arena(n)))
    return out


def train_pool(scen_count: int = 12, seed: int = SEED
               ) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Dict[str, Any]],
                          List[Tuple[str, Dict[str, Any]]]]:
    """(scen_pool, manifest, arenas) — стратифицированный TRAIN-пул. ho*/ho3_ исключены."""
    _ensure_server_path()
    pool, manifest = dataset.scenario_sources(scen_count, seed)
    arenas = arena_sources(TRAIN_ARENAS)
    return pool, manifest, arenas


def _is_attack(sample: Dict[str, Any]) -> bool:
    """Есть ли в плане учителя реальная атака (действие use) — отличаем атаку от без-атаки."""
    acts = (sample.get("meta") or {}).get("actions") or []
    return any(a.get("action") == "use" for a in acts)


def _admissible(sample: Dict[str, Any]) -> bool:
    """Метка лежит в A(s)? ensure_jointly_legal бросает ValueError на недопустимой/неканонической."""
    try:
        joint.ensure_jointly_legal(sample, spec3.SCHEMA)
        return True
    except ValueError:
        return False


def account_teacher(teacher: str, scen_count: int = 12, per_src: int = 6, rounds_max: int = 3,
                    seed: int = SEED) -> Dict[str, Any]:
    """Полный воронка-учёт одного учителя на стратифицированном пуле (схема 3).

    Делегирует в build_records + classify: УЧЁТ (1.1) и ПОСТРОЕНИЕ ВЫБОРКИ (часть 2/3) идут
    одним кодом, поэтому их числа идентичны по построению, а не «похожи».
    """
    records, skips, states = build_records(teacher, scen_count, per_src, rounds_max, seed)
    return classify(teacher, records, skips, states, seed=seed, per_src=per_src,
                    rounds_max=rounds_max)


def _tags(payload: Dict[str, Any], sample: Dict[str, Any]) -> Dict[str, Any]:
    """Семантические теги примера из payload-состояния (для QC-распределений, часть 3).

    attack_cell/end_cell восстанавливаются из порядка действий учителя (MOVE до USE = подход,
    после USE = уход); тип оружия/цель/добиваемость/размеры команд берутся из BattleContext.
    Это НЕ меняет пример и его legal/A(s) — только описание для отчёта."""
    ctx = BattleContext.from_payload(payload)
    acts = (sample.get("meta") or {}).get("actions") or []
    dirs_in, dirs_out, used, target_id, weapon_id = [], [], False, None, None
    for a in acts:
        kind = a.get("action")
        if kind == "target":
            target_id = a.get("conf", {}).get("id")
        elif kind == "move":
            (dirs_out if used else dirs_in).append(a.get("conf", {}).get("direction"))
        elif kind == "use":
            used, weapon_id = True, a.get("conf", {}).get("itemId")
    origin = ctx.src_cell
    attack_cell = apply_moves(origin, dirs_in)
    end_cell = apply_moves(origin, dirs_in + dirs_out)
    enemies = ctx.hostile_targets()
    tags: Dict[str, Any] = {
        "arena": (sample.get("meta") or {}).get("arena"),
        "schema": sample.get("schema"), "feat_version": sample.get("feat_version"),
        "is_attack": used,
        "retreat": bool(used and attack_cell != end_cell),
        "same_cell": attack_cell == end_cell,
        "allies": sum(1 for t in ctx.tokens if t.is_alive and not ctx.is_hostile(t)
                      and t.disposition == ctx.src.disposition and t.id != ctx.src_id) + 1,
        "enemies": len(enemies),
    }
    if used and weapon_id:
        w = ctx.weapon(weapon_id)
        tags["weapon"] = ("none" if w is None else
                          "thrown" if w.thrown else "ranged" if w.ranged else "melee")
        tgt = ctx.token(target_id) if target_id else None
        if tgt is not None and w is not None:
            tc = ctx.cell_of(tgt)
            d_chosen = cell_distance(attack_cell, tc)
            d_nearest = min([cell_distance(attack_cell, ctx.cell_of(e)) for e in enemies] or [d_chosen])
            tags["target_is_nearest"] = d_chosen <= d_nearest + 1e-9
            tags["target_killable"] = tgt.hp_current <= w.expected_damage
            tags["attack_distance"] = round(d_chosen, 3)
        tags["role"] = ("ranged" if any(x.ranged for x in ctx.weapons) else "melee")
    else:
        tags["weapon"] = "none"
        tags["role"] = "ranged" if any(x.ranged for x in ctx.weapons) else "melee"
    return tags


def build_records(teacher: str, scen_count: int = 12, per_src: int = 6, rounds_max: int = 3,
                  seed: int = SEED) -> Tuple[List[Dict[str, Any]], Dict[str, int], int]:
    """Собрать примеры схемы 3, РОВНО как dataset.generate (тот же sources()/variants()/pinned).

    Возвращает (records, skip_reasons, states): records = [{'sample','tags'}] по успешно
    размеченным состояниям; states = размеченные + пропущенные (знаменатель воронки).
    Контракт проверяем на месте: метка вне A(s) — стоп (не чиним и не отбрасываем молча).
    """
    _ensure_server_path()
    from arent.teacher import pinned
    pool, _manifest, _arenas = train_pool(scen_count, seed)
    teacher_impl = get_teacher(teacher, rounds=1, time_limit_sec=0.5)
    rng = random.Random(seed)
    records: List[Dict[str, Any]] = []
    skips: Dict[str, int] = {}
    states = 0
    with pinned(rounds=1, time_limit_sec=0.5):
        for name, payload in dataset.sources(want_arenas=None, use_live=False,
                                             exclude_independent=True, scenario_pool=pool,
                                             include_arenas=True):
            scene_seed = seed ^ zlib.crc32(name.encode("utf-8"))
            for state_payload, meta in variants(payload, rng, count=per_src,
                                                rounds_max=rounds_max):
                states += 1
                order = Simulation.of(BattleContext.from_payload(state_payload),
                                      env_seed=scene_seed).initiative_order
                sample, reason = dataset.sample_one_v3(name, state_payload, teacher_impl,
                                                       meta, order)
                if sample is None:
                    skips[reason] = skips.get(reason, 0) + 1
                    continue
                records.append({"sample": sample, "tags": _tags(state_payload, sample)})
    return records, skips, states


def _is_attack_record(rec: Dict[str, Any]) -> bool:
    return bool(rec["tags"]["is_attack"])


def classify(teacher: str, records: List[Dict[str, Any]], skips: Dict[str, int], states: int,
             seed: int = SEED, per_src: int = 6, rounds_max: int = 3) -> Dict[str, Any]:
    """Свести records+skips в воронку-учёт с контролем A(s) (без починки/отбрасывания)."""
    pool, _manifest, arenas = train_pool(seed=seed, scen_count=12)
    matched = len(records)
    attack = sum(1 for r in records if _is_attack_record(r))
    noattack = matched - attack
    atk_in = sum(1 for r in records if _is_attack_record(r) and _admissible(r["sample"]))
    na_in = sum(1 for r in records if not _is_attack_record(r) and _admissible(r["sample"]))
    atk_out, na_out = attack - atk_in, noattack - na_in
    no_attack_states = skips.get("no_attack", 0)
    no_slots = skips.get("no_slots", 0)
    label_out = skips.get("label_out_of_slots", 0)
    roundtrip = skips.get("roundtrip_mismatch", 0)
    formed = states - no_attack_states
    return {
        "teacher": teacher, "seed": seed, "per_src": per_src, "rounds_max": rounds_max,
        "sources": {"scenarios": len(pool), "arenas": len(arenas),
                    "arenas_seen": sorted({r["tags"]["arena"] for r in records
                                           if str(r["tags"].get("arena", "")).startswith(
                                               tuple(TRAIN_ARENAS))})},
        "states_received": states,
        "labels_no_attack_state": no_attack_states,
        "teacher_formed_action": formed,
        "matched_to_plan": matched,
        "unmatched": {"no_slots": no_slots, "label_out_of_slots": label_out,
                      "roundtrip_mismatch": roundtrip},
        "attack_labels": attack, "attack_in_As": atk_in, "attack_out_As": atk_out,
        "noattack_labels": noattack, "noattack_in_As": na_in, "noattack_out_As": na_out,
        "skip_reasons": skips,
        "groups": len({r["tags"]["arena"] for r in records}),
        "check_states": no_attack_states + formed == states,
        "check_formed": formed == matched + no_slots + label_out + roundtrip,
        "check_matched_split": attack + noattack == matched,
        "check_attack_As": atk_in + atk_out == attack,
        "check_noattack_As": na_in + na_out == noattack,
    }
