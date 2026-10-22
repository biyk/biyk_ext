# arent/evaluate.py — долгий горизонт как МЕТРИКА: сколько боёв политика реально выигрывает.
#
# train/bench меряют один ход (val.joint) и скорость. Здесь же политика сети играет ВЕСЬ
# бой в той же Simulation, что размечает учитель (враги отвечают жадно через foes_act), и
# мы считаем накопленную ценность линии, долю выживаний и долю зачисток. Это мост к дуэли
# (Фаза 2): вопрос «стало ли лучше» постепенно переезжает с угадывания одного хода на
# исход боя. Никакого обучения тут нет — только прогон чекпойнта по сценам.
import json
import os
from statistics import mean
from typing import Any, Callable, Dict, List, Optional, Tuple

from arent import backend, encode, encode_v3, joint as joint_mod, net, paths, play, provenance, spec, spec3
from arent import legalize as legalize_mod
from arent import slots as slots_mod, slots_v3
from arent.net import GROUPS, Y_KEY
from arent.observe import observe
from planner.context import BattleContext
from planner.scoring import Scorer
from planner.sim import Simulation

Row = Dict[str, Any]


def _schema_of(model) -> int:
    """Версия задачи модели (2 = клетка, 3 = move-plan); старые веса без cfg -> 2."""
    return int(getattr(getattr(model, "cfg", None), "schema", spec.SCHEMA))


def _dealt(prev_hp: Dict[str, float], state: Simulation) -> float:
    """Суммарный урон, полученный врагами за шаг актёра (только чтение hp, без правки боя)."""
    return round(sum(max(0.0, hp - state.units[u].hp)
                     for u, hp in prev_hp.items() if u in state.units), 4)


def _foe_hp(state: Simulation) -> Dict[str, float]:
    """id -> hp живых врагов героя (снапшот для измерения урона шаг-за-шагом)."""
    return {uid: u.hp for uid, u in state.units.items() if u.hostile_to_hero and u.is_alive}


def _attack_stat(raw: Dict[str, int], label: Dict[str, int], reason, slots: Any,
                 dealt: float) -> Dict[str, Any]:
    """Один раунд героя: счётчики РАЗНОГО смысла, не смешивать (Этап 7, часть 2).

    ``illegal`` — недопустимость НЕЗАВИСИМОГО baseline-предсказания голов (сырой argmax):
    он меряет старый декодер, а не ошибку политики; ``corrected`` — число вызовов legalize
    с фактической правкой (для joint-выбора обязано быть 0 = нарушение контракта, если нет);
    ``executed``/``zero_dmg`` — по реально исполненному действию.
    """
    nt, nw = len(slots.targets), len(slots.weapons)
    proposed = 0 <= raw.get("target", -1) < nt and 0 <= raw.get("weapon", -1) < nw
    executed = 0 <= label.get("target", -1) < nt and 0 <= label.get("weapon", -1) < nw
    return {"proposed": int(proposed), "executed": int(executed),
            "illegal": int(proposed and not executed),     # baseline-предсказание вне A(s)
            "corrected": int(bool(reason)),                 # действие изменено legalization
            "joint_violation": 0,                           # joint-выбор, починенный legalize
            "zero_dmg": int(executed and dealt <= 0.0)}     # исполненная атака без урона


def _round(model: Any, state: Simulation, schema: int) -> Tuple[Simulation, float, Dict[str, Any]]:
    """Один раунд героя: v3 идёт через move-plan и apply_actor_seq (удар из attack_cell,
    затем отступление), v2 — по-прежнему через клетку и advance. Ответ врагов — foes_act.
    Перед decode прогоняем ТУ ЖЕ совместную легальность, что и среда обучения."""
    ctx = state.context_for(state.hero_id)
    obs = observe(ctx)
    if schema == spec3.SCHEMA:
        slots = slots_v3.build(ctx, obs)
        sample = encode_v3.observation(ctx, obs, slots)
        out = model.predict(sample)                    # диагностический baseline (независимый argmax)
        yk = net.y_key(schema)
        raw = {yk[group]: out[yk[group]] for group in GROUPS}
        dec = joint_mod.decode(model, sample, slots, ctx, schema)   # выбор политики: joint-argmax
        label, reason = legalize_mod.legalize(dec["label"], schema, slots, ctx)
        hero_state = state.apply_actor_seq(state.hero_id, actions := slots_v3.decode(slots, label))
        dealt = _dealt(_foe_hp(state), hero_state)
        moved, penalty = hero_state.foes_act()
        stat = _attack_stat(raw, label, reason, slots, dealt)
        # нарушение контракта: joint-предложение было изменено защитным legalize
        stat["joint_violation"] = int(bool(reason) or dict(label) != dict(dec["label"]))
        return moved, Scorer().score(ctx, actions) + penalty, stat
    slots = slots_mod.build(ctx, obs)
    out = model.predict(encode.observation(ctx, obs, slots))
    raw = {Y_KEY[group]: out[Y_KEY[group]] for group in GROUPS}
    label, reason = legalize_mod.legalize(raw, schema, slots, ctx)
    actions = slots_mod.decode(slots, label)
    prev_hp = _foe_hp(state)
    moved, value = state.advance(actions)
    stat = _attack_stat(raw, label, reason, slots, _dealt(prev_hp, moved))
    return moved, value, stat


def fight(model: Any, payload: Dict[str, Any], rounds: int = 8) -> Dict[str, Any]:
    """Один бой политикой модели; копит ценность раундов Simulation.advance.

    Раунд: состояние -> наблюдение -> слоты -> предсказание сети -> decode -> advance
    (ход героя + ответ врагов) — ровно та же механика, что в rollout учителя, но вместо
    перебора hero_options() следующий ход выбирает обученная сеть. Стоп: герой погиб,
    врагов не осталось, или уперлись в потолок rounds.
    """
    state = Simulation.of(BattleContext.from_payload(payload))
    schema = _schema_of(model)
    total, played = 0.0, 0
    foes_total = len(state.foes)
    stat = {"proposed": 0, "executed": 0, "illegal": 0, "corrected": 0, "zero_dmg": 0,
            "joint_violation": 0}
    while played < max(1, int(rounds)) and not state.hero_dead and state.foes:
        state, value, step = _round(model, state, schema)
        total += value
        played += 1
        for k in stat:
            stat[k] += step[k]
    return {"rounds": played, "value": round(total, 3), "survived": not state.hero_dead,
            "cleared": not state.foes, "foes": foes_total, "foes_left": len(state.foes),
            "attacks_proposed": stat["proposed"], "attacks_executed": stat["executed"],
            "illegal_proposals": stat["illegal"], "corrected_actions": stat["corrected"],
            "policy_violations": stat["joint_violation"],
            "zero_damage_attacks": stat["zero_dmg"]}


def summarize(rows: List[Dict[str, Any]], model: str = "pure",
              rounds_cap: int = 0) -> Dict[str, Any]:
    """Список боёв -> сводка: средний исход + доли выживания/победы (все доли 0..1)."""
    n = max(1, len(rows))
    return {"fights": len(rows), "model": model, "rounds_cap": rounds_cap,
            "mean_value": round(mean([r["value"] for r in rows]) if rows else 0.0, 3),
            "survival_rate": round(sum(1 for r in rows if r["survived"]) / n, 3),
            "clear_rate": round(sum(1 for r in rows if r["cleared"]) / n, 3),
            "mean_rounds": round(mean([r["rounds"] for r in rows]) if rows else 0.0, 2),
            "rows": rows}


def _sources(arenas: Optional[List[str]], use_live: bool):
    """Сцены для прогона: символьные арены playground + живые снимки (как при генерации)."""
    from arent import dataset
    return list(dataset.sources(arenas, use_live))


def holdout_names(names: List[str], holdout_frac: float, seed: int) -> set:
    """Holdout-множество имён — то же, что режет rl (стабильно по frac/seed, val_frac не влияет)."""
    from arent.splitting import split_source_names
    _train, _val, holdout = split_source_names(names, holdout_frac, 0.0, seed)
    return set(holdout)


def _provenance(model_path: Optional[str], sources: List[Tuple[str, Dict[str, Any]]],
                rounds: int, set_tag: str = "all") -> Dict[str, Any]:
    """Якоря оценки: хеш конкретной модели, тестового набора и конфига — чтобы итог
    нельзя было приписать не той весовой паре. testset = сами payload'ы сцен (не имена).

    set_tag ('independent'/'holdout'/'all') фиксирует, по какому множеству считан итог —
    честное bc2↔PPO-сравнение валидно только при одинаковом set_tag='independent'."""
    names = [str(name) for name, _payload in sources]
    fingerprint = sorted([[str(name), payload] for name, payload in sources], key=lambda r: r[0])
    config = {"rounds": rounds, "sources": sorted(names), "model": model_path}
    return {"model_path": os.path.abspath(model_path) if model_path else None,
            "model_sha256": provenance.sha256_file(model_path) if model_path else None,
            "set_tag": set_tag, "test_sources": sorted(names),
            "testset_sha256": provenance.sha256_obj(fingerprint),
            "eval_config": config, "eval_config_sha256": provenance.sha256_obj(config)}


def run(name: str = "eval", model_path: Optional[str] = None, kind: str = "auto",
        arenas: Optional[List[str]] = None, use_live: bool = True, rounds: int = 8,
        out: Optional[str] = None, holdout_only: bool = False, holdout_frac: float = 0.3,
        split_seed: int = 7, independent: bool = False,
        independent_prefix: Optional[List[str]] = None,
        log: Optional[Callable] = None) -> Dict[str, Any]:
    """Прогнать чекпойнтом по всем сценам (или по выделенному набору); сводка в runs/<имя>/eval.json.

    independent=True — только зарезервированный независимый набор (ho_*): физически
    отделён от обучения bc2 и PPO, значит обе модели идут по одному и тому же честному
    множеству. independent_prefix сужает резерв по префиксу (напр. ["ho3_"] — только
    независимый набор схемы 3). holdout_only=True оставляет группы случайного split (независимы
    для PPO, но не гарантированно чисты от bc2). independent важнее holdout_only.
    """
    say = log or _echo
    # --model принимает и путь к model.json, и имя прогона (runs/<имя>/model.json) — как в play.
    requested = model_path
    if requested and not os.path.exists(requested):
        requested = play.latest_checkpoint(requested)
        if not requested:
            raise RuntimeError(f"Чекпойнта нет: runs/{model_path}/model.json отсутствует")
    model_path = requested or play.latest_checkpoint()
    if not model_path:
        raise RuntimeError("Чекпойнта нет: сначала arent train (или укажите --model)")
    model = backend.load_policy(model_path, kind=kind)
    if independent:
        from arent import dataset
        if independent_prefix:
            sources = dataset.independent_sources(arenas, use_live,
                                                  prefixes=tuple(independent_prefix))
        else:
            sources = dataset.independent_sources(arenas, use_live)
    else:
        sources = _sources(arenas, use_live)
        if holdout_only:
            keep = holdout_names([str(n) for n, _p in sources], holdout_frac, split_seed)
            sources = [(n, p) for n, p in sources if str(n) in keep]
    if not sources:
        raise RuntimeError("Нет сцен: арены playground пусты и живых снимков нет")
    tag = "independent" if independent else ("holdout" if holdout_only else "all")
    say(f"оценка {getattr(model, 'name', 'pure')} [{tag}] на {model_path}: {len(sources)} сцен, "
        f"потолок {rounds} раундов")
    rows: List[Row] = []
    for scene_name, payload in sources:
        row = dict(fight(model, payload, rounds), name=scene_name)
        rows.append(row)
        say(f"{scene_name}: раундов {row['rounds']}, ценность {row['value']}, "
            f"выжил {int(row['survived'])}, зачищено {int(row['cleared'])}")
    report = summarize(rows, model=getattr(model, "name", "pure"), rounds_cap=rounds)
    report["provenance"] = _provenance(model_path, sources, rounds, set_tag=tag)
    _write(paths.file_in(paths.run_dir(name), "eval.json"), report)
    say(f"итог: боёв {report['fights']}, выживаемость {report['survival_rate']}, "
        f"побед {report['clear_rate']}, средняя ценность {report['mean_value']}")
    if out:
        _write(out, report)
    return report


def _write(path: str, data: Any) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))


def _echo(*args: Any) -> None:
    print(*args, flush=True)
