# arent/team_eval.py — приёмочная метрика «универсального солдата»: win-rate КОМАНДЫ.
#
# evaluate.fight мерит старый моноакторный контур (герой + скриптовые foes_act, итог
# «выжил/зачистил»). Здесь — новый контур: каждый живой юнит обеих сторон ходит ОДНОЙ
# политикой через PolyFightEnv (self-play, WP3), итог боя — исход команды по TeamReward
# (win/loss/draw/mutual, WP4), эпизоды стартуют с разных актёров (start_index, WP5).
# Прогон детерминирован (среда считает ожиданием, predict — argmax), поэтому до/после
# сравнение на замороженном независимом наборе ho_/ho2_ честно для одних и тех же весов.
import os
import random
from statistics import mean
from typing import Any, Callable, Dict, List, Optional, Tuple

from arent import (backend, dataset, evaluate, joint as joint_mod, net, paths, play, polyenv,
                   spec, spec3, tactics_config, teachers)
from arent import slots as slots_mod, slots_v3
from arent.tactics_counters import Counters
from arent.tactics_shaper import TacticsShaper
from arent.team_reward import TeamReward

Row = Dict[str, Any]


def team_fight(model: Any, payload: Dict[str, Any], rounds_cap: int = 8,
               draw_window: int = 4, start_index: int = 0) -> Row:
    """Один бой: вся сцена ходит политикой модели, терминал — исход команды."""
    environment = polyenv.PolyFightEnv(rounds_cap=rounds_cap,
                                       team=TeamReward(draw_window=draw_window))
    obs = environment.reset(payload, start_index=start_index)
    start_actor = environment.actor
    steps, total, outcome, info = 0, 0.0, "open", {}
    while obs is not None:
        out = model.predict(obs)
        label = {k: int(out.get(k, -1)) for k in ("cell", "target", "weapon")}
        obs, reward, terminated, truncated, info = environment.step(label)
        steps += 1
        total += reward
        if terminated:
            outcome = info["outcome"]
            break
        if truncated:
            break                                       # усечение cap'ом: бой не решён
    alive = lambda hostile: sum(1 for u in environment.state.units.values()
                                if u.is_alive and u.hostile_to_hero == hostile)
    return {"outcome": outcome, "terminated": bool(info.get("terminated", False)),
            "rounds": int(info.get("rounds", 0)), "steps": steps,
            "reward": round(total, 4), "ours_alive": alive(False), "foes_alive": alive(True),
            "start_actor": start_actor}


def evaluate_sources(model: Any, sources: List[Tuple[str, Dict[str, Any]]],
                     rounds_cap: int = 8, draw_window: int = 4,
                     replays: int = 1) -> List[Row]:
    """Все сцены x replays повторов; повтор k стартует с k-го актёра (ротация WP5)."""
    rows: List[Row] = []
    for name, payload in sources:
        for rep in range(max(1, replays)):
            rows.append(dict(team_fight(model, payload, rounds_cap, draw_window,
                                        start_index=rep), name=name))
    return rows


def summarize_team(rows: List[Row], model: str = "pure", rounds_cap: int = 0) -> Row:
    """Доли исходов команды (0..1) + средняя длительность; «open» — дожившие до cap."""
    n = max(1, len(rows))
    rate = lambda outcome: round(sum(1 for r in rows if r["outcome"] == outcome) / n, 4)
    return {"fights": len(rows), "model": model, "rounds_cap": rounds_cap,
            "win_rate": rate("win"), "loss_rate": rate("loss"), "draw_rate": rate("draw"),
            "mutual_rate": rate("mutual"), "open_rate": rate("open"),
            "mean_rounds": round(mean([r.get("rounds", 0) for r in rows]) if rows else 0.0, 2),
            "mean_reward": round(mean([r.get("reward", 0.0) for r in rows]) if rows else 0.0, 3),
            "rows": rows}


def run(name: str = "team_eval", model_path: Optional[str] = None, kind: str = "auto",
        arenas: Optional[List[str]] = None, use_live: bool = True, rounds_cap: int = 8,
        draw_window: int = 4, replays: int = 1, independent: bool = True,
        out: Optional[str] = None, log: Optional[Callable] = None) -> Row:
    """Прогнировать чекпойнтом командным контуром; сводка в runs/<имя>/team_eval.json.

    independent=True — только ho_/ho2_ (физически отделён от train/reward bc2 и PPO):
    именно так сравниваются «до» (моноакторный evaluate.run) и «после» (этот прогон)
    на одних весах и одном честном множестве с якорями provenance.
    """
    say = log or _echo
    requested = model_path
    if requested and not os.path.exists(requested):
        requested = play.latest_checkpoint(requested)
        if not requested:
            raise RuntimeError(f"Чекпойнта нет: runs/{model_path}/model.json отсутствует")
    model_path = requested or play.latest_checkpoint()
    if not model_path:
        raise RuntimeError("Чекпойнта нет: сначала arent train/rl (или укажите --model)")
    model = backend.load_policy(model_path, kind=kind)
    if independent:
        sources = dataset.independent_sources(arenas, use_live)
    else:
        sources = list(dataset.sources(arenas, use_live, exclude_independent=True))
    if not sources:
        raise RuntimeError("Нет сцен: арены playground пусты и живых снимков нет")
    tag = "independent" if independent else "non-independent"
    say(f"командная оценка {getattr(model, 'name', 'pure')} [{tag}] на {model_path}: "
        f"{len(sources)} сцен x{replays}, cap {rounds_cap} раундов")
    rows = evaluate_sources(model, sources, rounds_cap, draw_window, replays)
    report = summarize_team(rows, model=getattr(model, "name", "pure"), rounds_cap=rounds_cap)
    report["provenance"] = evaluate._provenance(model_path, sources, rounds_cap, set_tag=tag)
    for row in rows:
        say(f"{row['name']}: исход {row['outcome']}, раундов {row['rounds']}, "
            f"наш живых {row['ours_alive']}, врагов {row['foes_alive']}")
    evaluate._write(paths.file_in(paths.run_dir(name), "team_eval.json"), report)
    say(f"итог: win {report['win_rate']}, loss {report['loss_rate']}, "
        f"draw {report['draw_rate']}, mutual {report['mutual_rate']}, "
        f"open {report['open_rate']}")
    if out:
        evaluate._write(out, report)
    return report


# --- командный матчбокс ДВУХ политик (Этап 1) --------------------------------- #
#
# team_fight выше водит ОБЕ стороны ОДНОЙ политикой (self-play). Здесь — то, чего
# не хватало для честной оценки: КАНДИДАТ ведёт всю свою команду, СОПЕРНИК — явно
# заданная фиксированная политика (greedy/battlecast/другие веса), и обе стороны ходят
# через ТОТ ЖЕ PolyFightEnv, что и обучение (legalize -> slots.decode -> apply_actor[_seq]
# -> TeamReward). Никакой отдельной упрощённой боевой логики нет: политики лишь выдают
# тройку индексов в пространство среды, а исполняет их Simulation. Итог разворачивается к
# перспективе кандидата; в matchup_sources стороны A/B меняются местами (side-swap).

ENV_MODE = "team-2policy"

#: имена, под которыми matchup понимает случайного соперника-baseline (§10.3).
RANDOM_OPPONENTS = frozenset({"random", "random_policy", "RandomPolicy"})


def env_version(schema: int) -> Row:
    """Версия боевого контура (среда/схема/терминал) — в каждый ряд журнала."""
    return {"env": "PolyFightEnv", "schema": int(schema), "team": "TeamReward", "mode": ENV_MODE}


class ModelController:
    """Политика весов: схема 3 — общий joint-декодер (тот же, что play/evaluate), схема 2 — argmax.

    last_baseline — диагностический независимый argmax голов (старый serving до Этапа 7):
    им меряют «недопустимость независимого предсказания», не смешивая с действиями политики.
    """

    _is_controller = True

    def __init__(self, model: Any, schema: Optional[int] = None):
        self.model = model
        self.schema = int(schema if schema is not None else
                          getattr(getattr(model, "cfg", None), "schema", spec.SCHEMA))
        yk = net.y_key(self.schema)
        self.keys = (yk["cells"], yk["targets"], yk["weapons"])
        self.name = getattr(model, "name", "model")
        self.last_baseline: Optional[Dict[str, int]] = None

    def describe(self) -> str:
        return "%s@schema%d" % (self.name, self.schema)

    def label(self, obs: Dict[str, Any], ctx: Any, slots: Any) -> Dict[str, int]:
        if self.schema == spec3.SCHEMA:
            # выбор политики — максимум совместной вероятности по A(s); среда приложила
            # obs['legal'], поэтому маска та же, что породила наблюдение (serve==train)
            dec = joint_mod.decode(self.model, obs, slots, ctx, self.schema)
            self.last_baseline = joint_mod.independent_baseline(dec["logp"], self.schema)
            return dec["label"]
        out = self.model.predict(obs)
        self.last_baseline = None
        return {k: int(out.get(k, -1)) for k in self.keys}


class TeacherController:
    """Фиксированная политика-учитель: plan(ctx) -> индексы слотов той же среды.

    Слоты мутируются на месте (ensure_cell/ensure_plan) ровно так же, как при разметке BC,
    поэтому env.step декодирует и исполняет план учителя той же Simulation, что и модель —
    без отдельной боевой логики учителя. Fallback «стоять/не атаковать», если план учителя
    не лёг в слоты (у greedy/battlecast финальная клетка всегда достижима, так что не бывает).
    """

    _is_controller = True

    def __init__(self, teacher: Any, schema: Optional[int] = None):
        self.teacher = teacher
        self.schema = int(schema if schema is not None else spec.SCHEMA)
        self.name = getattr(teacher, "name", type(teacher).__name__)
        self.last_baseline: Optional[Dict[str, int]] = None      # у учителя нет голов-baseline

    def describe(self) -> str:
        return "%s@schema%d" % (self.name, self.schema)

    def label(self, obs: Dict[str, Any], ctx: Any, slots: Any) -> Dict[str, int]:
        actions = self.teacher.plan(ctx)
        if self.schema == spec3.SCHEMA:
            slots_v3.ensure_plan(slots, ctx, actions)
            lab = slots_v3.label_of(ctx, slots, actions)
            return lab or {"plan": 0, "target": spec.NONE_SLOT, "weapon": spec.NONE_SLOT}
        slots_mod.ensure_cell(slots, ctx.src_cell, slots_mod.final_cell(ctx, actions),
                              slots_mod.dirs_of(actions))
        lab = slots_mod.label_of(ctx, slots, actions)
        return lab or {"cell": 0, "target": spec.NONE_SLOT, "weapon": spec.NONE_SLOT}


class RandomController:
    """Случайный соперник-baseline (§10.3): равномерный выбор по совместному A(s)=obs['legal'].

    Ни весов, ни учителя — только uniform по тем же совместно допустимым тройкам, что видит
    PPO-политика, поэтому serve==train по множеству действий (выбранная тройка уже совместна,
    защитный legalize среды — тождество). Нужен как нижняя граница честного matchup: «модель не
    хуже случайного» (§0.1). Детерминирован по seed: один rng на прогон, порядок шагов фиксирует
    среда; last_baseline всегда None (нет голов для независимого baseline).
    """

    _is_controller = True

    def __init__(self, seed: int = 0, schema: Optional[int] = None):
        self.schema = int(schema if schema is not None else spec.SCHEMA)
        yk = net.y_key(self.schema)
        self.keys = (yk["cells"], yk["targets"], yk["weapons"])
        self.rng = random.Random(seed)
        self.name = "random"
        self.last_baseline: Optional[Dict[str, int]] = None

    def describe(self) -> str:
        return "random@schema%d" % self.schema

    def label(self, obs: Dict[str, Any], ctx: Any, slots: Any) -> Dict[str, int]:
        mask = obs.get("legal") if isinstance(obs, dict) else None
        if mask is None:
            mask = joint_mod.legal_mask(slots, ctx, self.schema)
        triples = [(p, t, w) for p, rows in enumerate(mask)
                   for t, cols in enumerate(rows) for w, ok in enumerate(cols) if ok]
        pos_k, tgt_k, wpn_k = self.keys
        if not triples:                       # контракт A(s) непусто (есть no-attack на позицию)
            return {pos_k: 0, tgt_k: spec.NONE_SLOT, wpn_k: spec.NONE_SLOT}
        p, t, w = self.rng.choice(triples)
        return {pos_k: p, tgt_k: t, wpn_k: w}


def build_controller(policy: Any, schema: Optional[int] = None):
    """Контроллер из уже собранного (.label+._is_controller), имени учителя или модели-весов."""
    if getattr(policy, "_is_controller", False):
        if schema is not None:
            policy.schema = int(schema)
        return policy
    if isinstance(policy, str):
        if policy in RANDOM_OPPONENTS:
            return RandomController(schema=schema)
        if policy in teachers.list_teachers():
            return TeacherController(teachers.get_teacher(policy, rounds=1, time_limit_sec=None),
                                     schema)
    return ModelController(policy, schema)


def _flip_outcome(outcome: str, candidate_is_foes: bool) -> str:
    """Исход якорен по hero (src). Если кандидат на стороне врагов — win/loss зеркалятся."""
    if not candidate_is_foes:
        return outcome
    return {"win": "loss", "loss": "win"}.get(outcome, outcome)


def fight_teams(payload: Dict[str, Any], candidate: Any, opponent: Any,
                candidate_is_foes: bool = False, rounds_cap: int = 8, draw_window: int = 4,
                start_index: int = 0, schema: Optional[int] = None,
                trace_limit: int = 0, counters: Optional[Counters] = None) -> Row:
    """Командный бой двух политик через PolyFightEnv; итог — с точки зрения кандидата.

    Каждый живой актёр обеих сторон по инициативе ходит контроллером СВОЕЙ команды; ход
    исполняет среда. candidate_is_foes задаёт, какую сторону ведёт кандидат (A/B-swap).
    trace (первые trace_limit шагов, 0 = все) — доказательство, что ходили обе команды.

    counters: если передан — среда обвешивается record_only-шейпером (§1.1: детекторы/счётчики
    идут по ground-truth трасса, но в награду НЕ текут, reward остаётся честным исходом).
    """
    candidate = build_controller(candidate, schema)
    opponent = build_controller(opponent, candidate.schema)
    environment = polyenv.PolyFightEnv(rounds_cap=rounds_cap,
                                       team=TeamReward(draw_window=draw_window),
                                       schema=candidate.schema)
    if counters is not None:
        shape = tactics_config.config()
        if shape.enabled_global:
            environment.set_shaper(TacticsShaper(shape, shape.allowed(None), counters,
                                                 record_only=True))
    obs = environment.reset(payload, start_index=start_index)
    start_actor = environment.actor
    steps, total, outcome, info = 0, 0.0, "open", {}
    illegal = zero_dmg = cand_steps = opp_steps = 0
    # РАЗДЕЛЬНЫЕ счётчики (не смешиваем, Этап 7 часть 2): недопустимое предложение,
    # исправленное действие, реально исполненная атака, исполненная атака с нулевым уроном —
    # по ВСЕМУ бою. «illegal_proposals» считает НЕдопустимость ВЫБРАННОГО политикой действия
    # (для joint-декодера = 0); независимый baseline голов — отдельным счётчиком.
    illegal_prop = corrected = exec_attacks = zero_dmg_attacks = 0
    # То же, но только по КАНДИДАТУ (его оцениваем; соперник — фиксированная политика).
    ci_prop = ci_corr = ci_exec = ci_zero = 0
    # Диагностический независимый argmax голов (старый декодер): доля его предложений вне A(s)
    # и число вызовов/фактических правок защитного legalize по кандидату.
    ci_base = ci_base_outside = ci_legalize_calls = ci_outside = 0
    trace: List[Row] = []
    while obs is not None:
        actor = environment.actor
        side_foe = bool(environment.state.units[actor].hostile_to_hero)
        is_candidate = (side_foe == candidate_is_foes)
        ctrl = candidate if is_candidate else opponent
        before = {uid: u.hp for uid, u in environment.state.units.items()}
        chosen = ctrl.label(obs, environment._ctx, environment.slots)
        baseline = getattr(ctrl, "last_baseline", None)
        nt, nw = len(environment.slots.targets), len(environment.slots.weapons)
        obs_legal = obs.get("legal") if isinstance(obs, dict) else None
        if counters is not None:
            counters.gate(is_candidate)      # §8-I: в статистику — только шаги кандидата
        obs, reward, terminated, truncated, info = environment.step(chosen)
        executed = info["action"]
        reason = info.get("legalize_reason")
        dealt = round(sum(max(0.0, before[uid] - environment.state.units[uid].hp)
                          for uid in before if uid in environment.state.units), 4)
        proposed_attack = (0 <= int(chosen.get("target", -1)) < nt
                           and 0 <= int(chosen.get("weapon", -1)) < nw)
        executed_attack = (0 <= int(executed.get("target", -1)) < nt
                           and 0 <= int(executed.get("weapon", -1)) < nw)
        is_illegal = dict(executed) != dict(chosen)
        is_illegal_prop = proposed_attack and not executed_attack   # политика хотела недопустимое
        policy_outside = (obs_legal is not None
                          and not joint_mod.is_jointly_legal(chosen, obs_legal, candidate.schema))
        illegal += int(is_illegal)
        zero_dmg += int(dealt <= 0.0)
        illegal_prop += int(is_illegal_prop)
        corrected += int(is_illegal)
        exec_attacks += int(executed_attack)
        zero_dmg_attacks += int(executed_attack and dealt <= 0.0)
        cand_steps += int(is_candidate)
        opp_steps += int(not is_candidate)
        if is_candidate:
            ci_prop += int(is_illegal_prop)
            ci_corr += int(is_illegal)
            ci_exec += int(executed_attack)
            ci_zero += int(executed_attack and dealt <= 0.0)
            ci_legalize_calls += 1                       # среда зовёт legalize на каждый шаг
            ci_outside += int(policy_outside)            # выбранное политикой вне A(s) (не должно)
            if baseline is not None:
                ci_base += 1
                bt, bw = int(baseline.get("target", -1)), int(baseline.get("weapon", -1))
                base_attack = 0 <= bt < nt and 0 <= bw < nw
                base_outside = base_attack and not joint_mod.is_jointly_legal(
                    baseline, obs_legal, candidate.schema) if obs_legal is not None else False
                ci_base_outside += int(base_outside)
        if (not trace_limit) or steps < trace_limit:
            trace.append({"step": steps, "actor": actor, "side": "cand" if is_candidate else "opp",
                          "proposed": dict(chosen), "chosen": dict(chosen),
                          "executed": dict(executed), "reason": reason,
                          "proposed_attack": proposed_attack, "executed_attack": executed_attack,
                          "illegal": is_illegal, "policy_outside": policy_outside,
                          "dealt": dealt, "zero_damage": dealt <= 0.0,
                          "value": info.get("value")})
        steps += 1
        total += reward
        if terminated:
            outcome = info["outcome"]
            break
        if truncated:
            break
    alive = lambda foe: sum(1 for u in environment.state.units.values()
                            if u.is_alive and bool(u.hostile_to_hero) == foe)
    cand_alive = alive(candidate_is_foes)
    opp_alive = alive(not candidate_is_foes)
    end_reason = ("terminated:%s" % outcome if info.get("terminated")
                  else ("truncated:rounds_cap" if info.get("truncated") else "open"))
    return {"outcome": _flip_outcome(outcome, candidate_is_foes), "raw_outcome": outcome,
            "candidate": candidate.name, "opponent": opponent.name,
            "candidate_id": candidate.describe(), "opponent_id": opponent.describe(),
            "candidate_is_foes": bool(candidate_is_foes), "schema": candidate.schema,
            "env_version": env_version(candidate.schema),
            "terminated": bool(info.get("terminated", False)),
            "truncated": bool(info.get("truncated", False)), "end_reason": end_reason,
            "rounds": int(info.get("rounds", 0)), "steps": steps,
            "candidate_steps": cand_steps, "opponent_steps": opp_steps,
            "reward": round(total, 4), "candidate_alive": cand_alive, "opponent_alive": opp_alive,
            "illegal_steps": illegal, "zero_damage_steps": zero_dmg,
            "illegal_proposals": illegal_prop, "corrected_actions": corrected,
            "attacks_executed": exec_attacks, "attacks_zero_damage": zero_dmg_attacks,
            "cand_illegal_proposals": ci_prop, "cand_corrected": ci_corr,
            "cand_attacks_executed": ci_exec, "cand_attacks_zero_damage": ci_zero,
            "cand_baseline_steps": ci_base, "cand_baseline_outside_As": ci_base_outside,
            "cand_legalize_calls": ci_legalize_calls, "cand_policy_outside_As": ci_outside,
            "start_actor": start_actor, "trace": trace}


def matchup_sources(candidate: Any, opponent: Any, sources: List[Tuple[str, Dict[str, Any]]],
                    rounds_cap: int = 8, draw_window: int = 4, replays: int = 1,
                    swap_sides: bool = True, trace_limit: int = 0,
                    counters: Optional[Counters] = None) -> List[Row]:
    """Каждая сцена x replays x обе расстановки сторон (candidate то hero-команда, то foes)."""
    candidate = build_controller(candidate)
    opponent = build_controller(opponent, candidate.schema)
    rows: List[Row] = []
    for name, payload in sources:
        for rep in range(max(1, replays)):
            for cand_foes in ((False, True) if swap_sides else (False,)):
                row = fight_teams(payload, candidate, opponent, cand_foes, rounds_cap,
                                  draw_window, start_index=rep, schema=candidate.schema,
                                  trace_limit=trace_limit, counters=counters)
                rows.append(dict(row, name=name, replay=rep))
    return rows


def summarize_matchup(rows: List[Row], rounds_cap: int = 8, draw_window: int = 4) -> Row:
    """Доли исходов КАНДИДАТА: сводно и раздельно по каждой расстановке сторон (A/B)."""
    def _block(sub: List[Row]) -> Row:
        n = max(1, len(sub))
        rate = lambda o: round(sum(1 for r in sub if r["outcome"] == o) / n, 4)
        return {"fights": len(sub),
                "win_rate": rate("win"), "loss_rate": rate("loss"), "draw_rate": rate("draw"),
                "mutual_rate": rate("mutual"), "open_rate": rate("open"),
                "mean_rounds": round(mean([r["rounds"] for r in sub]) if sub else 0.0, 2),
                "mean_reward": round(mean([r["reward"] for r in sub]) if sub else 0.0, 3),
                "mean_illegal_steps": round(mean([r["illegal_steps"] for r in sub]) if sub else 0.0, 3),
                "mean_zero_damage_steps": round(mean([r["zero_damage_steps"] for r in sub]) if sub else 0.0, 3),
                "mean_illegal_proposals": round(mean([r.get("illegal_proposals", 0) for r in sub]) if sub else 0.0, 3),
                "mean_attacks_executed": round(mean([r.get("attacks_executed", 0) for r in sub]) if sub else 0.0, 3),
                "mean_attacks_zero_damage": round(mean([r.get("attacks_zero_damage", 0) for r in sub]) if sub else 0.0, 3)}
    return {"mode": ENV_MODE, "rounds_cap": rounds_cap, "draw_window": draw_window,
            "candidate_id": rows[0]["candidate_id"] if rows else None,
            "opponent_id": rows[0]["opponent_id"] if rows else None,
            "fights": len(rows), "overall": _block(rows),
            "candidate_is_hero_team": _block([r for r in rows if not r["candidate_is_foes"]]),
            "candidate_is_foe_team": _block([r for r in rows if r["candidate_is_foes"]]),
            "rows": rows}


def _resolve_controller(policy: Any, kind: str, schema: Optional[int], random_seed: int = 0):
    """Спецификация стороны -> контроллер: случайный baseline, имя учителя, путь/имя весов."""
    if isinstance(policy, str):
        if policy in RANDOM_OPPONENTS:
            return RandomController(seed=random_seed, schema=schema), policy
        if policy in teachers.list_teachers():
            return TeacherController(teachers.get_teacher(policy, rounds=1, time_limit_sec=None),
                                     schema), policy
        path = policy
        if not os.path.exists(path):
            path = play.latest_checkpoint(path)
        if not path:
            raise RuntimeError("Нет ни учителя %r, ни чекпойнта runs/%s/model.json"
                               % (policy, policy))
        return ModelController(backend.load_policy(path, kind=kind), schema), path
    return build_controller(policy, schema), getattr(policy, "describe", lambda: "?")()


def run_matchup(candidate: str, opponent: str, name: str = "team_matchup", kind: str = "auto",
                arenas: Optional[List[str]] = None, use_live: bool = True, rounds_cap: int = 8,
                draw_window: int = 4, replays: int = 1, swap_sides: bool = True,
                independent: bool = True, trace_limit: int = 0, out: Optional[str] = None,
                log: Optional[Callable] = None, use_tactics: bool = False,
                random_seed: int = 0,
                scenario_sources: Optional[List[Tuple[str, Dict[str, Any]]]] = None) -> Row:
    """Матчбокс двух политик на одном наборе стартовых состояний; сводка в team_matchup.json.

    Отдельный файл (не перезаписывает team_eval.json/eval.json): командная оценка двух
    политик живёт раздельно и от одиночного evaluate, и от self-play team_eval.

    scenario_sources: явный пул (name, payload) вместо выборки с диска — так гоняют
    сгенерированные дуэли Этапа 1, НЕ записывая их в боевой каталог арен (зеркалит rl.run).
    """
    say = log or _echo
    cand_ctrl, cand_id = _resolve_controller(candidate, kind, None, random_seed)
    opp_ctrl, opp_id = _resolve_controller(opponent, kind, cand_ctrl.schema, random_seed)
    if scenario_sources is not None:
        sources = list(scenario_sources)
        tag = "explicit-pool"
    elif independent:
        sources = dataset.independent_sources(arenas, use_live)
        tag = "independent"
    else:
        sources = list(dataset.sources(arenas, use_live, exclude_independent=True))
        tag = "non-independent"
    if not sources:
        raise RuntimeError("Нет сцен: арены playground пусты и живых снимков нет")
    say("матчбокс %s vs %s [%s]: %d сцен x%d, cap %d, swap %s"
        % (cand_ctrl.describe(), opp_ctrl.describe(), tag, len(sources), replays,
           rounds_cap, swap_sides))
    counters = Counters() if use_tactics else None
    rows = matchup_sources(cand_ctrl, opp_ctrl, sources, rounds_cap, draw_window, replays,
                           swap_sides, trace_limit, counters=counters)
    report = summarize_matchup(rows, rounds_cap, draw_window)
    if counters is not None:
        report["tactics"] = counters.to_dict()
    report["provenance"] = evaluate._provenance(cand_id if cand_id.endswith(".json") else None,
                                                sources, rounds_cap, set_tag=tag)
    report["provenance"]["candidate"] = cand_id
    report["provenance"]["opponent"] = opp_id
    for row in rows:
        say("%s r%d [%s]: исход %s, раундов %d, наш жив %d, враж %d, шагов к/о %d/%d"
            % (row["name"], row["replay"], "foes" if row["candidate_is_foes"] else "ours",
               row["outcome"], row["rounds"], row["candidate_alive"], row["opponent_alive"],
               row["candidate_steps"], row["opponent_steps"]))
    evaluate._write(paths.file_in(paths.run_dir(name), "team_matchup.json"), report)
    ov = report["overall"]
    say("итог: win %s, loss %s, draw %s, mutual %s, open %s (у кандидата)"
        % (ov["win_rate"], ov["loss_rate"], ov["draw_rate"], ov["mutual_rate"], ov["open_rate"]))
    if out:
        evaluate._write(out, report)
    return report


def _echo(*args: Any) -> None:
    print(*args, flush=True)
