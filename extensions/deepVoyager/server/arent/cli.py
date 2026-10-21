# arent/cli.py — точки входа: gen (выборка), train (обучение), play (ход), info (окружение).
#
# Это то же самое, что вызывает exe: `arent gen --count 400`, `arent train --epochs 30`,
# `arent play --arena corridor_archer`. Пути — вокруг рабочего каталога (arent/paths.py),
# поэтому --home переключает и данные, и runs/ целиком.
import argparse
import json
import os
import sys
import time
from typing import List, Optional

from arent import abset, backend, bench, compare, dataset, evaluate, holdout, net, paths, play, spec, teachers, train


def _utf8_stdout() -> None:
    """Windows в cp1251 спотыкается о кириллицу и юникодные стрелки в выводе."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="arent", description="обучение нейроагента хода NPC")
    ap.add_argument("--home", help="рабочая папка arent: рядом с ней лежат data/ и runs/")
    sub = ap.add_subparsers(dest="cmd")

    gen = sub.add_parser("gen", help="сгенерировать выборку учителем-планировщиком")
    defaults = net.gen_defaults()
    gen.add_argument("--name", default=defaults.get("name", "bc"))
    gen.add_argument("--count", type=int, default=defaults.get("count", 200))
    gen.add_argument("--seed", type=int, default=defaults.get("seed", 7))
    gen.add_argument("--per-src", type=int, default=defaults.get("per_src", 4))
    gen.add_argument("--rounds-max", type=int, default=defaults.get("rounds_max", 3))
    gen.add_argument("--teacher-rounds", type=int, default=defaults.get("teacher_rounds", 2))
    gen.add_argument("--teacher-limit", type=float, default=defaults.get("teacher_limit", 1.0))
    gen.add_argument("--teacher", default=defaults.get("teacher", teachers.DEFAULT_TEACHER),
                     choices=teachers.list_teachers(),
                     help="политика-учитель разметки (по умолчанию greedy)")
    gen.add_argument("--shallow-k", type=int, default=defaults.get("shallow_k"))
    gen.add_argument("--top-k", type=int, default=defaults.get("top_k"))
    gen.add_argument("--arena", nargs="*", default=None, help="имена арен playground")
    gen.add_argument("--no-live", action="store_true", help="не брать снимки из data/payloads")
    gen.add_argument("--append", action="store_true",
                    help="дописать в существующую выборку, пропустив уже размеченные состояния")

    tr = sub.add_parser("train", help="behavior cloning по выборке из data/samples")
    tr.add_argument("--dataset", help="имя выборки или путь к .jsonl (по умолчанию — свежая)")
    tr.add_argument("--warm", help="довыучивать от чекпойнта: имя прогона в runs/ или путь")
    tr.add_argument("--val", help="отдельная выборка для проверки (старые сценарии)")
    tr.add_argument("--name", default="latest", help="подпапка в runs/")
    tr.add_argument("--epochs", type=int)
    tr.add_argument("--batch", type=int)
    tr.add_argument("--lr", type=float)
    tr.add_argument("--hidden", type=int)
    tr.add_argument("--head", type=int)
    tr.add_argument("--kind", default="auto", choices=["auto", "torch", "pure"])
    tr.add_argument("--device", choices=["auto", "cuda", "cpu"],
                    help="куда класть сеть (для pure всегда cpu)")

    bn = sub.add_parser("bench", help="замер времени: pure / torch+cpu / torch+cuda")
    bn.add_argument("--dataset", help="имя выборки или путь к .jsonl")
    bn.add_argument("--name", default="bench")
    bn.add_argument("--epochs", type=int, default=5)
    bn.add_argument("--batch", type=int)
    bn.add_argument("--kinds", nargs="*", default=["pure", "torch"])
    bn.add_argument("--devices", nargs="*", default=["cpu", "cuda"])

    pl = sub.add_parser("play", help="сыграть чекпойнтом по снимку сцены")
    pl.add_argument("--model", help="runs/<имя>/model.json (по умолчанию — самый свежий)")
    pl.add_argument("--payload", help="JSON-файл с запросом формата /plan")
    pl.add_argument("--arena", help="имя арены playground")
    pl.add_argument("--out", help="куда записать результат")
    pl.add_argument("--kind", default="auto", choices=["auto", "torch", "pure"])

    ev = sub.add_parser("evaluate", help="сыграть чекпойнтом целые бои: исход, а не один ход")
    ev.add_argument("--model", help="runs/<имя>/model.json (по умолчанию — самый свежий)")
    ev.add_argument("--name", default="eval", help="подпапка в runs/ для eval.json")
    ev.add_argument("--rounds", type=int, default=8, help="потолок раундов в одном бою")
    ev.add_argument("--arena", nargs="*", default=None, help="имена арен playground")
    ev.add_argument("--no-live", action="store_true", help="не брать снимки из data/payloads")
    ev.add_argument("--out", help="куда дополнительно записать сводку")
    ev.add_argument("--kind", default="auto", choices=["auto", "torch", "pure"])
    ev.add_argument("--holdout-only", action="store_true",
                    help="гонять только по независимому holdout-набору (те же frac/seed, что у rl)")
    ev.add_argument("--independent", action="store_true",
                    help="только зарезервированный независимый набор ho_* (вне bc2 и вне PPO)")
    ev.add_argument("--holdout-frac", type=float, default=0.3, help="доля групп в holdout")
    ev.add_argument("--split-seed", type=int, default=7, help="seed группового split (как у rl)")

    rlp = sub.add_parser("rl", help="PPO над итогом боя: долгосрочный горизонт политическим градиентом")
    rlp.add_argument("--warm", default="bc2", help="родитель весов: имя прогона (model_best.json) или путь; '' — со случайных")
    rlp.add_argument("--no-warm", action="store_true", help="не делать warm-start: обучение со случайных весов")
    rlp.add_argument("--name", default="ppo", help="подпапка в runs/")
    rlp.add_argument("--iters", type=int)
    rlp.add_argument("--rollout", type=int, help="шагов rollout на итерацию")
    rlp.add_argument("--gamma", type=float)
    rlp.add_argument("--gae-lambda", type=float)
    rlp.add_argument("--clip", type=float)
    rlp.add_argument("--ent", type=float)
    rlp.add_argument("--vf", type=float)
    rlp.add_argument("--ppo-epochs", type=int)
    rlp.add_argument("--minibatch", type=int)
    rlp.add_argument("--rounds", type=int, help="потолок раундов в episode")
    rlp.add_argument("--replays", type=int, help="повторов на сцену в eval")
    rlp.add_argument("--seed", type=int)
    rlp.add_argument("--lr", type=float, help="шаг актёра-критика")
    rlp.add_argument("--clear-bonus", type=float, help="терминальная награда за зачистку")
    rlp.add_argument("--death-penalty", type=float, help="терминальная награда за гибель")
    rlp.add_argument("--team-reward", action="store_true",
                     help="v2: командная награда ±5 (исход/kill/hit/living + окно пата) вместо одиночного героя")
    rlp.add_argument("--reward-scale", type=float, help="делитель сырого значения симуляции для полосы ±5")
    rlp.add_argument("--draw-window", type=int, help="раундов подряд без событий -> пат (DRAW)")
    rlp.add_argument("--holdout-frac", type=float, help="доля групп сцен, зарезервированных под оценку")
    rlp.add_argument("--val-frac", type=float, help="доля остатка под отбор чекпойнта")
    rlp.add_argument("--variants", type=int, help="вариантов стартового состояния на train-сцену")
    rlp.add_argument("--no-reset-value-head", action="store_true",
                     help="перенести критик из BC (по умолчанию критик инициализируется заново)")
    rlp.add_argument("--no-vref", action="store_true",
                     help="выключить потенциальный shaping от замороженного V_ref")
    rlp.add_argument("--resume", action="store_true",
                     help="продолжить с ppo_state.pt (оптимизатор/итерация/RNG), если он есть")
    rlp.add_argument("--arena", nargs="*", default=None, help="имена арен playground")
    rlp.add_argument("--no-live", action="store_true", help="не брать снимки из data/payloads")
    rlp.add_argument("--device", choices=["auto", "cuda", "cpu"], help="куда класть сеть (RL требует torch)")
    rlp.add_argument("--kind", default="torch", choices=["auto", "torch", "pure"])

    ab = sub.add_parser("abtest", help="сравнить учителей на одинаковых сценах (без обучения)")
    ab.add_argument("--teachers", nargs="*", default=["greedy", "battlecast"],
                    choices=teachers.list_teachers(), help="имена политик из реестра")
    ab.add_argument("--seed", type=int, default=11)
    ab.add_argument("--per-src", type=int, default=4)
    ab.add_argument("--rounds-max", type=int, default=2)
    ab.add_argument("--teacher-rounds", type=int, default=1)
    ab.add_argument("--rounds", type=int, default=8, help="потолок раундов в closed-loop")
    ab.add_argument("--arena", nargs="*", default=None, help="имена арен playground")
    ab.add_argument("--live", action="store_true", help="добавить живые снимки из data/payloads")
    ab.add_argument("--name", default="ab", help="подпапка в runs/ для teacher_ab.json")

    abs_ = sub.add_parser("abset", help="A/B учителей на фиксированном независимом наборе (без обучения)")
    abs_.add_argument("--teachers", nargs="*", default=["greedy", "battlecast"],
                      choices=teachers.list_teachers(), help="имена политик из реестра")
    abs_.add_argument("--count", type=int, default=80, help="число сгенерированных независимых боёв")
    abs_.add_argument("--seed", type=int, default=20261020, help="seed фиксированного набора сцен")
    abs_.add_argument("--teacher-rounds", type=int, default=1)
    abs_.add_argument("--rounds", type=int, default=8, help="потолок раундов в closed-loop")
    abs_.add_argument("--ci-seed", type=int, default=1234, help="seed bootstrap-интервалов")
    abs_.add_argument("--depth", nargs=2, action="append", metavar=("TEACHER", "ROUNDS"),
                      help="глубина lookahead учителя (напр. --depth greedy 3); по умолчанию teacher-rounds")
    abs_.add_argument("--limit", nargs=2, action="append", metavar=("TEACHER", "SEC"),
                      help="дедлайн планировщика на план для учителя (напр. --limit greedy 0.5)")
    abs_.add_argument("--name", default="abset", help="подпапка в runs/ для fixed_set.json/abset.json")

    hld = sub.add_parser("holdout", help="создать замороженный командный holdout v2 (ho2_* арены)")
    hld.add_argument("--count", type=int, default=holdout.HOLDOUT_COUNT, help="число сцен в наборе")
    hld.add_argument("--seed", type=int, default=holdout.HOLDOUT_SEED, help="фиксированное семя набора")
    hld.add_argument("--out", help="каталог арен (по умолчанию playground/arenas)")
    hld.add_argument("--manifest", help="куда писать манифест происхождения набора")

    sub.add_parser("info", help="чем считаем, где данные, сколько весов")
    return ap


def _gen(args) -> int:
    started = time.monotonic()
    samples, stats = dataset.generate(count=args.count, seed=args.seed, per_src=args.per_src,
                                      rounds_max=args.rounds_max, teacher_rounds=args.teacher_rounds,
                                      teacher_limit=args.teacher_limit, want_arenas=args.arena,
                                      use_live=not args.no_live, shallow_k=args.shallow_k,
                                      top_k=args.top_k, teacher=args.teacher)
    took = time.monotonic() - started
    if args.append:
        path, added, total = dataset.append(samples, args.name, stats)
        print(f"новых {added}, всего в выборке {total} -> {path} "
              f"(размечено {len(samples)} за {took:.1f} с)")
    else:
        path = dataset.save(samples, args.name, stats)
        print(f"примеров {len(samples)} за {took:.1f} с ({len(samples) / max(took, 1e-9):.2f} шт/с) "
              f"-> {path}")
    print(json.dumps(stats, ensure_ascii=False, indent=1, sort_keys=True))
    return 0 if samples else 1


def _train(args) -> int:
    cfg = net.default_config()
    val = dataset.load(args.val) if args.val else None
    train.run(name=args.name, dataset_name=args.dataset, cfg=cfg, kind=args.kind,
              epochs=args.epochs, batch=args.batch, lr=args.lr, hidden=args.hidden,
              head=args.head, warm=args.warm, device=args.device, val=val)
    return 0


def _bench(args) -> int:
    bench.run(name=args.name, dataset_name=args.dataset, epochs=args.epochs, batch=args.batch,
              kinds=tuple(args.kinds), devices=tuple(args.devices))
    return 0


def _play(args) -> int:
    play.run(model_path=args.model, payload_path=args.payload, arena=args.arena,
             out=args.out, kind=args.kind)
    return 0


def _evaluate(args) -> int:
    report = evaluate.run(name=args.name, model_path=args.model, kind=args.kind,
                          arenas=args.arena, use_live=not args.no_live, rounds=args.rounds,
                          out=args.out, holdout_only=args.holdout_only,
                          holdout_frac=args.holdout_frac, split_seed=args.split_seed,
                          independent=args.independent)
    return 0 if report["fights"] else 1


def _rl(args) -> int:
    # torch-зависимые модули импортируем только здесь: `arent info|train|play` обязаны
    # работать на машине без torch (формат чекпойнта общий), а RL-ветка torch требует.
    from arent import rl, rollout
    fields = {"iters": args.iters, "rollout_steps": args.rollout, "gamma": args.gamma,
              "gae_lambda": args.gae_lambda, "clip_eps": args.clip, "ent_coef": args.ent,
              "vf_coef": args.vf, "ppo_epochs": args.ppo_epochs, "minibatch": args.minibatch,
              "rounds_cap": args.rounds, "replays": args.replays, "seed": args.seed,
              "lr": args.lr, "clear_bonus": args.clear_bonus, "death_penalty": args.death_penalty,
              "use_team_reward": args.team_reward,
              "reward_scale": args.reward_scale, "draw_window": args.draw_window,
              "holdout_frac": args.holdout_frac, "val_frac": args.val_frac,
              "variants_per_src": args.variants}
    rcfg = rollout.RlConfig(**{k: v for k, v in fields.items() if v is not None})
    if args.no_reset_value_head:
        rcfg.reset_value_head = False
    if args.no_vref:
        rcfg.use_vref = False
    warm = None if args.no_warm else (args.warm or None)
    result = rl.run(name=args.name, warm=warm, rcfg=rcfg, net_cfg=net.default_config(),
                    kind=args.kind, device=args.device, arenas=args.arena,
                    use_live=not args.no_live, resume=args.resume)
    best = result.get("best") or {}
    print(json.dumps({"model": result["checkpoint"], "model_best": result["best_checkpoint"],
                      "best_closed_loop": best}, ensure_ascii=False, indent=1, sort_keys=True))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    _utf8_stdout()
    try:
        args = parser().parse_args(argv)
    except SystemExit as stop:                        # --help и ошибки argparse — тоже код
        return int(stop.code or 0)
    if args.home:
        paths.set_workspace(args.home)
    if not args.cmd:
        print("нет команды: arent gen | train | bench | play | evaluate | rl | info (--help по параметрам)")
        return 2
    handlers = {"gen": _gen, "train": _train, "bench": _bench, "play": _play,
                "evaluate": _evaluate, "rl": _rl, "abtest": _abtest, "abset": _abset,
                "holdout": _holdout, "info": lambda _a: _info()}
    try:
        return handlers[args.cmd](args)
    except (RuntimeError, FileNotFoundError, ValueError) as error:
        print(f"ошибка: {error}")
        return 1


def _abtest(args) -> int:
    report = compare.run(seed=args.seed, per_src=args.per_src, rounds_max=args.rounds_max,
                         teacher_rounds=args.teacher_rounds, rounds=args.rounds,
                         teachers=tuple(args.teachers), arenas=args.arena, use_live=args.live)
    path = paths.file_in(paths.run_dir(args.name), "teacher_ab.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"сцен {report['n_scenarios']} (независимый набор исключён), состояний {report['n_states']} "
          f"-> {path}")
    for name in report["teachers"]:
        loop, samp = report["closed_loop"][name], report["sampling"][name]
        print(f"  {name}: выживание {loop['survival_rate']}, зачистка {loop['clear_rate']}, "
              f"раундов {loop['mean_rounds']}, урон +{loop['mean_dmg_dealt']}/-{loop['mean_dmg_taken']} "
              f"| метка {samp['label_rate']}, общий rollout {report['quality'][name]['mean_common_rollout']} "
              f"| {samp['ms_per_state']} мс/состояние")
    return 0


def _abset(args) -> int:
    depth_map = {name: int(r) for name, r in (args.depth or [])}
    limit_map = {name: float(s) for name, s in (args.limit or [])}
    report = abset.run(count=args.count, seed=args.seed, rounds=args.rounds,
                       teacher_rounds=args.teacher_rounds, teachers=tuple(args.teachers),
                       ci_seed=args.ci_seed, depth_map=depth_map, limit_map=limit_map)
    paths.run_dir(args.name)
    out = abset.write(report, paths.run_dir(args.name))
    g, b = report["teachers"][0], (report["teachers"][1] if len(report["teachers"]) > 1 else report["teachers"][0])
    print(f"независимых сцен {report['n_scenes']} (holdout исключён), fingerprint {report['set_fingerprint'][:12]} "
          f"-> {out['result']}")
    for name in report["teachers"]:
        pt = report["per_teacher"][name]
        d = report["depths"][name]
        print(f"  {name} [rounds={d['rounds']}, limit={d['time_limit_sec']}]: "
              f"выживание {pt['survival_rate']}, зачистка {pt['clear_rate']}, "
              f"раундов {pt['mean_rounds']}, rollout {pt['mean_rollout']}, "
              f"урон +{pt['mean_dmg_dealt']}/-{pt['mean_dmg_taken']} "
              f"| метка {pt['coverage']['label_rate']} | {pt['ms_per_fight']} мс/бой")
    print(f"  парная разность {g}-{b} (mean [ci_lo, ci_hi]):")
    for metric, st in report["paired"]["diff_stats"].items():
        print(f"    {metric}: {st['mean']} [{st['ci_lo']}, {st['ci_hi']}] "
              f"(доля сцен в плюс {g}: {st['positive_share']})")
    return 0


def _holdout(args) -> int:
    """Создать/обновить замороженный командный holdout v2 (ho2_*). Набор детерминирован seed."""
    res = holdout.author(count=args.count, seed=args.seed, out_dir=args.out, manifest=args.manifest)
    print(f"заморожено ho2_* арен: {res['written']} -> {res['dir']}")
    print("  " + ", ".join(res["names"]))
    if res["manifest"]:
        print(f"  манифест -> {res['manifest']}")
    return 0 if res["written"] else 1


def _info() -> int:
    report = {"workspace": paths.describe(), "backend": backend.describe(),
              "dims": spec.dims()}
    print(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True))
    return 0
