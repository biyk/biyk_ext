#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Парсер боевых трейсов .ray -> battles.json / battles.js для trace_viewer.

Читает ТРИ источника (только read-only чужих файлов):
  1) stage3_traces_*.log        — чистый UTF-8, без разбора наград;
  2) stage3_reward_hack*.log    — UTF-16 LE с mojibake (консольная перекодировка),
     содержит строки «награда ... = base ... + as-if такт [...]»;
  3) traces_all_*.json          — машиночитаемый дамп .ray/dump_traces.py (ВСЕ бои,
     включая победы; нативные поля team_eval: rows[].trace[].reward_breakdown).

Разбор логов структурный: все числовые/технические поля (координаты, id, теги, веса)
— ASCII-якоря, поэтому не зависят от mojibake; кириллица (названия оружия,
фразы) чинится посимвольной таблицей MOJIBAKE для отображения.

Запуск:  python parse_traces.py [--out <dir>] [файл ...]
Без аргументов — сканирует ../.ray/stage3_traces_*.log, stage3_reward_hack*.log
и traces_all_*.json.
"""
import argparse
import glob
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_GLOBS = [
    os.path.join(HERE, "..", "..", ".ray", "stage3_traces_*.log"),
    os.path.join(HERE, "..", "..", ".ray", "stage3_reward_hack*.log"),
    os.path.join(HERE, "..", "..", ".ray", "traces_all_*.json"),
    os.path.join(HERE, "..", "..", ".ray", "traces_win_*.json"),
]
RAY_DIR = os.path.normpath(os.path.join(HERE, "..", "..", ".ray"))
GATE_LOG_GLOB = os.path.join(RAY_DIR, "stage3_imitate*.log")

# --- structural anchors (ASCII) ------------------------------------------------
HDR_RE = re.compile(
    r"===\s*[^\s=]+\s+([A-Za-z0-9_]+):\s*(\w+)\s+vs\s*(\w+)\s*\|"
    r"\s*[^\s=]+=([a-z]+)\s*\(([^)]*)\)\s*\|\s*[^\s=]+=(\d+)\s+[^\s=]+=(\d+)")
STEP_RE = re.compile(
    r"\[(cand|opp)\]\s+([AF]\w+):\s*\[(\d+),\s*(\d+)\]\s*->\s*\[(\d+),\s*(\d+)\]\s*\|\s*(.*)$")
BOARD_RE = re.compile(
    r"([AF])([AF]\w+)\s*hp([+-]?[\d.]+)@\[(\d+),\s*(\d+)\]")
REW_RE = re.compile(
    r"([+-]?[\d.]+)\s*=\s*base\s*([+-]?[\d.]+)\s*\+\s*[^+|]*\s([+-]?[\d.]+)"
    r"\s*\+\s*[^|]*\s([+-]?[\d.]+)(.*)$")
ASIF_RE = re.compile(r"as-if\s+[^\d+-]*([+-]?[\d.]+)\s*\[([^\]]*)\]")
TAG_ITEM_RE = re.compile(
    r"^([+-]?)([^\s+-]+?)([+-]?\d*\.?\d+)$")
NUM_RE = re.compile(r"[+-]?\d+\.?\d*")
LEGAL_RE = re.compile(r"\(([a-z_]{6,}[^)]*)\)")
PAIR_RE = re.compile(r"(mobile_archer|melee|fast|reach|ranged|tank)"
                     r"v(mobile_archer|melee|fast|reach|ranged|tank)")
# гейт-этап обучения: строки «s3_vs_<opponent> : win=.. bootCI>=.. loss=.. draw=.. [PASS/FAIL]»
# и закрывающая «STAGE3 GATE (<label>): PASS/FAIL». ASCII-якоря — не зависят от mojibake.
VS_RE = re.compile(
    r"s3_vs_(\w+)\s*:\s*win=([0-9.]+)\s+bootCI>=([0-9.]+)\s+loss=([0-9.]+)"
    r"\s+draw=([0-9.]+).*?\[(PASS|FAIL)")
GATE_RE = re.compile(r"STAGE3 GATE \((.*?)\):\s*(PASS|FAIL)")

# --- таблица починки mojibake (символ-из-лога -> настоящий символ) -------------
MOJIBAKE = {
    "°": "ш", "р": "а", "у": "г", "ф": "д", "ю": "о", "ё": "с", "ъ": "к",
    "э": "н", "Ё": "р", "я": "п", "Є": "т", "х": "е", "ч": "з", "с": "б",
    "Ў": "ц", "ь": "м", "№": "ь", "╕": "ё", "ї": "х", "т": "в", "ш": "и",
    "√": "ы", "щ": "й", "ы": "л", "─": "Д", "╠": "М", "┬": "В", "╨": "Н",
    "┼": "И", "═": "М", "╬": "М", "·": "в", ">": "л", "■": "",
}
# известные фиксированные подстроки (надёжнее посимвольной починки)
PHRASE_FIX = {
    "─ышээ√щ ыєъ": "Длинный лук", "·>эчэ√щ ъєъ": "Длинный лук",
    "Длиннлй лгк": "Длинный лук", "╠хў": "Меч", "▒хў": "Меч",
    "Мез": "Меч", "Боевой вопоа": "Боевой топор", "Двгагзнлй": "Двуручный",
    "┬╨┼─═╬": "ВНИМ", "яюых": "field", "поле": "field",
}


def fix_text(s):
    """Починка отображаемой кириллицы: сначала фразы, затем посимвольно."""
    if not s:
        return s
    for bad, good in PHRASE_FIX.items():
        if bad in s:
            s = s.replace(bad, good)
    return "".join(MOJIBAKE.get(ch, ch) for ch in s)


def read_text(path):
    """-> (text, mojibake?). UTF-16 BOM -> utf-16; флаг mojibake по маркеру."""
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")
    return text, ("°ру" in text or "сющ" in text)


def parse_tags(blob):
    out = []
    for tok in blob.split():
        m = TAG_ITEM_RE.match(tok)
        if not m:
            continue
        sign, raw_name, raw_num = m.groups()
        name = PHRASE_FIX.get(raw_name, raw_name)
        if name in ("поле", "яюых", "field"):
            name = "field"
        elif re.search(r"[^a-z_]", name):
            name = fix_text(name)
        if not re.match(r"^[a-z_]+$", name):
            continue
        try:
            w = float(raw_num) if raw_num not in ("", "+", "-") else 0.0
        except ValueError:
            continue
        if raw_num[:1] not in "+-" and sign == "-":
            w = -w
        if w == 0.0:
            continue
        out.append({"name": name, "w": w})
    return out


def parse_step_tail(rest, moj=False):
    """Часть строки шага после '...-> [x, y] | ' -> (target, weapon, dmg, legal)."""
    segs = [s.strip() for s in rest.split("|")]
    target = weapon = legal = None
    dmg = 0.0
    if segs:
        m = re.search(r"\b([AF]\d)\b", segs[0])
        if m:
            target = m.group(1)
            wm = re.search(r"[«·л]([^»|]+?)[»╗]|«([^»]+)»", segs[0])
            if wm:
                raw = (wm.group(1) or wm.group(2)).strip()
                if moj:
                    fixed = fix_text(raw)
                    weapon = PHRASE_FIX.get(raw) or PHRASE_FIX.get(fixed) or fixed
                else:
                    weapon = raw
                weapon = weapon.strip("«» ")
    if len(segs) > 1:
        nm = NUM_RE.search(segs[1])
        if nm:
            dmg = float(nm.group(0))
        lm = LEGAL_RE.search(segs[1])
        if lm:
            legal = lm.group(0)
    return target, weapon, dmg, legal


def parse_reward_tail(line, moj=False):
    """Строка 'награда X = base ... [ | as-if такт Y [tags] ] [<<< warn]'."""
    m = REW_RE.search(line)
    if not m:
        return None
    total, base, pot, tact, tail = m.groups()
    rw = {"total": float(total), "base": float(base),
          "potential": float(pot), "tactical_applied": float(tact),
          "asif": None, "tags": [], "warn": None}
    am = ASIF_RE.search(tail)
    if am:
        rw["asif"] = float(am.group(1))
        rw["tags"] = parse_tags(am.group(2))
    if "<<<" in tail:
        w = fix_text(tail.split("<<<", 1)[1].lstrip(": ").strip()) if moj \
            else tail.split("<<<", 1)[1].lstrip(": ").strip()
        if w.startswith("ВНИМ") and moj:  # канонический вариант (mojibake необратим)
            w = "ВНИМ: не атакует, но получает +тактический"
        rw["warn"] = w
    return rw


def classes_from_sid(sid):
    m = PAIR_RE.search(sid or "")
    return (m.group(1), m.group(2)) if m else (None, None)


# --- traces_all_*.json (дамп .ray/dump_traces.py, нативные поля team_eval) ------
def tags_from_native(t):
    """{fired, violated, weights, field, asif} -> [{name, w}] как в парсере логов."""
    out = []
    weights = t.get("weights") or {}
    for k in t.get("fired") or []:
        w = float(weights.get(k, 0.0))
        if w:
            out.append({"name": k, "w": w})
    for k in t.get("violated") or []:
        w = -abs(float(weights.get(k, 0.0)))          # violated — штраф, как в «-tag%g» лога
        if w:
            out.append({"name": k, "w": w})
    f = float(t.get("field", 0.0) or 0.0)
    if f:
        out.append({"name": "field", "w": f})
    return out


def reward_from_native(ts):
    rb = ts.get("reward_breakdown") or {}
    if not rb:
        return None
    t = rb.get("tags") or {}
    asif = t.get("asif") if t else None
    rw = {"total": float(ts.get("reward", 0.0) or 0.0),
          "base": float(rb.get("base", 0.0) or 0.0),
          "potential": float(rb.get("potential", 0.0) or 0.0),
          "tactical_applied": float(rb.get("tactical_applied", 0.0) or 0.0),
          "asif": asif, "tags": tags_from_native(t), "warn": None}
    if asif and asif > 1e-9 and not ts.get("executed_attack"):
        rw["warn"] = "ВНИМ: не атакует, но получает +тактический"
    return rw


def arena_geometry(arena, c_max, r_max):
    """row['arena'] (dump_traces с 24.10) -> (grid, walls, field-метка).
    Клетки board/tokens в дампе — [row,col]; вьюер рисует X=col, Y=row,
    поэтому w = ширина поля в клетках (горизонталь), h = высота. Без арены —
    авто-размер по координатам (как раньше). Стены px -> клетки; нормированные
    размеры берём максимумом с координатами: единицы могут выходить за декларируемое поле."""
    sc = (arena or {}).get("scene") or {}
    gs = float(sc.get("gridSize") or 0) or 50.0
    if sc.get("width") and sc.get("height"):
        gw = max(int(sc["width"] // gs), int(c_max + 1))
        gh = max(int(sc["height"] // gs), int(r_max + 1))
    else:
        gw, gh = int(max(c_max + 1, 12)), int(max(r_max + 1, 8))
    walls = []
    for w in (arena or {}).get("walls") or []:
        try:
            a, b = w["points"]["A"], w["points"]["B"]
            walls.append([round(float(a["x"]) / gs, 3), round(float(a["y"]) / gs, 3),
                          round(float(b["x"]) / gs, 3), round(float(b["y"]) / gs, 3)])
        except (KeyError, TypeError, ValueError):
            continue
    field = None
    if arena:
        field = {"profile": arena.get("field_profile"), "archetype": arena.get("archetype"),
                 "deployment": arena.get("deployment"), "layout": arena.get("layout"),
                 "n_walls": arena.get("n_walls")}
    return {"w": gw, "h": gh}, walls, field


def parse_json_file(path, obs_dir=None):
    """traces_all/win_*.json {run, set, rows:[team_eval-нативные]} -> бои формата вьюера.

    Набор (set): "winrate" (стандартный канон) | "chaos" (учебный). Берём из row['set'],
    иначе из top-level d['set'], иначе по имени файла (traces_win_* -> winrate). Legacy-бои
    из логов и старые дампы без поля -> "chaos" (галочка вьюера по умолчанию их и показывает).

    obs_dir: если задан — каждый шаг дампа с obs_input (team_eval obs_trace=cand|all)
    выгружается sidecar-файлом obs/<battle_uid>_step<N>.json, а в battle.js остаётся лишь
    ссылка st["obsFile"]. Сами obs_input из rows ВЫРЕЗАЮТСЯ — иначе battles.js раздуется.
    Перед записью боя его прежние sidecar-файлы удаляются (защита от stale-шагов)."""
    d = json.load(open(path, encoding="utf-8"))
    run = d.get("run", "?")
    fname = os.path.basename(path)
    file_set = d.get("set") or ("winrate" if fname.startswith("traces_win") else "chaos")
    battles = []
    for r in d.get("rows", []):
        name = r.get("name", "?")
        b_uid = r.get("battle_uid")
        if obs_dir and b_uid:                     # прежнее поколение этого боя — долой
            for old in glob.glob(os.path.join(obs_dir, "%s_step*.json" % b_uid)):
                try:
                    os.remove(old)
                except OSError:
                    pass
        cls_a, cls_f = classes_from_sid(name)
        steps, r_max, c_max = [], -1.0, -1.0     # board-клетки [row,col]: row~Y, col~X
        actors, hp_max = set(), {}
        has_tags = has_rew = False
        for i, ts in enumerate(r.get("trace", [])):
            board = {}
            for ent in ts.get("board") or []:
                uid, hp, cell = ent[0], float(ent[3]), ent[4]
                board[uid] = {"hp": hp, "cell": cell}
                hp_max[uid] = max(hp_max.get(uid, 0.0), hp)
                r_max = max(r_max, cell[0])
                c_max = max(c_max, cell[1])
            atk = ts.get("attack") or {}
            rw = reward_from_native(ts)
            if rw:
                has_rew = True
                if rw["tags"]:
                    has_tags = True
            actors.add(ts.get("actor"))
            obs_in = ts.pop("obs_input", None)    # в battles.js не тащим — только sidecar
            steps.append({"kind": ts.get("side"), "actor": ts.get("actor"),
                          "from": ts.get("cell_before"), "to": ts.get("cell_after"),
                          # rich v3 (с 26.10): полный маршрут шага и клетка удара; в старых
                          # дампов нет -> None, вьюер откатывается на прямую from->to
                          "path": ts.get("path"), "attackCell": ts.get("attackCell"),
                          "attackTarget": atk.get("target"), "weapon": atk.get("weapon"),
                          "damage": float(ts.get("dealt", 0.0) or 0.0),
                          "legalize": ts.get("reason"), "board": board, "reward": rw,
                          "n": i})
            if obs_in is not None and obs_dir and b_uid:
                os.makedirs(obs_dir, exist_ok=True)
                leaf = "%s_step%d.json" % (b_uid, int(ts.get("step", i)))
                with open(os.path.join(obs_dir, leaf), "w", encoding="utf-8") as fo:
                    json.dump(obs_in, fo, ensure_ascii=False)   # прямой UTF-8: без mojibake
                steps[-1]["obsFile"] = "obs/" + leaf
        n_act = max(1, len(actors))
        grid, walls, field = arena_geometry(r.get("arena"), c_max, r_max)
        # arena.tokens -> экипировка на бойца (клик на карте показывает оружие/характеристики)
        gear = {t.get("id"): {"name": t.get("name"), "hp": t.get("hp"),
                              "speed": t.get("speed"), "reachFt": t.get("reachFt"),
                              "hitChance": t.get("hitChance"), "init": t.get("initiative"),
                              "weapons": t.get("weapons") or []}
                for t in (r.get("arena") or {}).get("tokens") or []}
        for st in steps:
            st["round"] = st["n"] // n_act
        units = {"A1": {"side": "hero", "cls": cls_a, "hpMax": hp_max.get("A1", 0)},
                 "F1": {"side": "foe", "cls": cls_f, "hpMax": hp_max.get("F1", 0)}}
        battles.append({
            "id": name, "file": fname, "block": "%s vs %s" % (r.get("candidate", run),
                                                               r.get("opponent", "?")),
            "policy": r.get("candidate", run), "opponent": r.get("opponent", "?"),
            "outcome": r.get("outcome"),
            "set": r.get("set") or file_set,
            "candSide": "foes" if r.get("candidate_is_foes") else "heroes",
            "rounds": int(r.get("rounds", 0)), "stepsDeclared": int(r.get("steps", len(steps))),
            # метрики сторон из team_eval.fight_teams (r7): нанёс/получил/очки + стабильный uid.
            "battleUid": r.get("battle_uid"),
            "dealt": _fnum(r.get("cand_dealt")), "taken": _fnum(r.get("cand_taken")),
            "points": _fnum(r.get("cand_points")),
            "hasRewardLines": has_rew, "hasTags": has_tags,
            "pair": name, "units": units, "steps": steps, "gear": gear,
            "grid": grid, "walls": walls, "field": field})
    return battles


def parse_file(path, only_reward=False):
    text, moj = read_text(path)
    if only_reward and not moj:
        return []  # трассировочный лог без разбора наград тут не нужен
    battles, cur, pending, name = [], None, None, os.path.basename(path)
    x_max = y_max = -1.0
    for line in text.splitlines():
        h = HDR_RE.search(line)
        if h and line.strip().startswith("==="):
            sid, pol, opp, outcome, side_phr, rounds, steps_n = h.groups()
            cls_a, cls_f = classes_from_sid(sid)
            cands = fix_text(side_phr) if moj else side_phr
            cand_side = "foes" if ("враг" in cands or "тЁр" in side_phr) else "heroes"
            cur = {"id": sid, "file": name, "block": "%s vs %s" % (pol, opp),
                   "policy": pol, "opponent": opp, "outcome": outcome,
                   "candSide": cand_side,
                   "rounds": int(rounds), "stepsDeclared": int(steps_n),
                   "hasRewardLines": False, "hasTags": False, "pair": sid,
                   "units": {"A1": {"side": "hero", "cls": cls_a},
                             "F1": {"side": "foe", "cls": cls_f}},
                   "steps": []}
            battles.append(cur)
            pending = None
            continue
        s = STEP_RE.search(line)
        if s and cur is not None:
            kind, actor, x1, y1, x2, y2, rest = s.groups()
            tgt, wpn, dmg, legal = parse_step_tail(rest, moj)
            rw = parse_reward_tail(line) if "base" in line else None
            step = {"kind": kind, "actor": actor,
                    "from": [int(x1), int(y1)], "to": [int(x2), int(y2)],
                    "attackTarget": tgt, "weapon": wpn, "damage": dmg,
                    "legalize": legal, "board": None, "reward": None}
            cur["steps"].append(step)
            pending = step
            for c in (step["from"], step["to"]):
                x_max, y_max = max(x_max, c[0]), max(y_max, c[1])
            continue
        b = BOARD_RE.search(line)
        if b and cur is not None and pending is not None and "hp" in line:
            board = {}
            for side, uid, hp, bx, by in BOARD_RE.findall(line):
                board[uid] = {"hp": float(hp), "cell": [int(bx), int(by)]}
                x_max, y_max = max(x_max, int(bx)), max(y_max, int(by))
            pending["board"] = board
            for uid, u in cur["units"].items():
                if uid in board:
                    u["hpMax"] = max(u.get("hpMax", 0), board[uid]["hp"])
            pending = None
            continue
        if cur is not None and cur["steps"] and ("= base" in line
                                                 or "эруЁрфр" in line):
            rw = parse_reward_tail(line, moj)
            if rw:
                cur["steps"][-1]["reward"] = rw
                cur["hasRewardLines"] = True
                if rw["tags"]:
                    cur["hasTags"] = True
    for bt in battles:
        n = max(1, len({s["actor"] for s in bt["steps"]}))
        for i, st in enumerate(bt["steps"]):
            st["n"] = i
            st["round"] = i // n
        bt["grid"] = {"w": int(max(x_max + 1, 12)), "h": int(max(y_max + 1, 8))}
    return battles


def drop_untagged_dupes(paths):
    """traces_all_X_tagged.json заменяет собой traces_all_X.json (те же бои + as-if-теги).
    При скане по умолчанию не удваиваем список боёв: если рядом лежит _tagged-версия — берём её."""
    names = {os.path.basename(p) for p in paths}
    keep = []
    for p in paths:
        b = os.path.basename(p)
        if b.endswith(".json") and not b.endswith("_tagged.json") \
                and (b[:-len(".json")] + "_tagged.json") in names:
            continue
        keep.append(p)
    return keep


def _fnum(v):
    """None/пусто -> None; число -> float (метрик нет в legacy-дампе)."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def aggregate_roles(battles):
    """Сводка боевых метрик по роли кандидата: раздельно за героев и за врагов.

    Группирует по (policy, candSide); считает нанёс/получил/очки (среднее по боям, где
    метрики есть) и винрейт кандидата. Бои с battle_uid учитываются ОДИН раз (дедуп —
    один и тот же бой мог попасть из двух дампов); legacy-бои без uid считаются как есть.
    Бой без разбора сторон (dealt/taken оба None — старый дамп до r7) в сводку не берётся.
    -> list[dict] для таблицы во вкладке «Статистика».
    """
    seen, buckets = set(), {}
    for b in battles:
        uid = b.get("battleUid")
        if uid:
            if uid in seen:
                continue
            seen.add(uid)
        dealt, taken = b.get("dealt"), b.get("taken")
        if dealt is None and taken is None:
            continue
        acc = buckets.setdefault((b.get("policy", "?"), b.get("candSide", "?")),
                                 {"n": 0, "wins": 0, "dealt": 0.0, "taken": 0.0, "ws": 0})
        acc["n"] += 1
        if b.get("outcome") == "win":
            acc["wins"] += 1
        acc["ws"] += 1
        acc["dealt"] += dealt or 0.0
        acc["taken"] += taken or 0.0
    rows = []
    for (pol, role), acc in buckets.items():
        n, ws = acc["n"], acc["ws"]
        rows.append({"policy": pol, "role": role, "fights": n, "wins": acc["wins"],
                     "win_rate": round(acc["wins"] / n, 4) if n else 0.0,
                     "mean_dealt": round(acc["dealt"] / ws, 2) if ws else None,
                     "mean_taken": round(acc["taken"] / ws, 2) if ws else None,
                     "mean_points": round((acc["dealt"] - acc["taken"]) / ws, 2) if ws else None,
                     "stat_fights": ws})
    rows.sort(key=lambda r: (r["policy"], r["role"]))
    return rows


def extract_gate(glob_path=None):
    """Винрейты гейта «до (BC) / после (BC+PPO)» из последнего stage3_imitate*.log.
    -> data['gate'] для таблицы во вкладке «Статистика». Нет логов/блоков -> None.
    Чистое чтение: берём самый свежий лог, внутри него — последний блок на стадию
    (PPO-блок содержит '+PPO' в лейбле, BC-гейт — нет). Детерминировано по файлу."""
    logs = sorted(glob.glob(glob_path or GATE_LOG_GLOB), key=os.path.getmtime)
    if not logs:
        return None
    try:
        text, _moj = read_text(logs[-1])
    except OSError:
        return None
    blocks, order, pending = {}, [], []
    for line in text.splitlines():
        vm = VS_RE.search(line)
        if vm:
            opp, win, ci, loss, draw, verdict = vm.groups()
            try:
                pending.append({"opponent": opp, "win": float(win), "ci": float(ci),
                                "loss": float(loss), "draw": float(draw),
                                "verdict": verdict})
            except ValueError:
                pass
            continue
        gm = GATE_RE.search(line)
        if gm and pending:
            label = gm.group(1).strip()
            blocks[label] = {"rows": pending, "verdict": gm.group(2)}
            order.append(label)
            pending = []
    if not blocks:
        return None
    after_label = next((l for l in reversed(order) if "PPO" in l), None)
    before_label = next((l for l in reversed(order) if "PPO" not in l), None)
    after = blocks.get(after_label) if after_label else None
    before = blocks.get(before_label) if before_label else None

    def rmap(blk):
        return {r["opponent"]: r for r in blk["rows"]} if blk else {}
    bm, am = rmap(before), rmap(after)
    base = (after or before or {}).get("rows", [])
    opps = list(dict.fromkeys([r["opponent"] for r in base]))
    rows = []
    for opp in opps:
        b, a = bm.get(opp), am.get(opp)
        rows.append({"opponent": opp,
                     "before_win": b["win"] if b else None,
                     "before_ci": b["ci"] if b else None,
                     "before_verdict": b["verdict"] if b else None,
                     "after_win": a["win"] if a else None,
                     "after_ci": a["ci"] if a else None,
                     "after_verdict": a["verdict"] if a else None})
    return {"log": os.path.basename(logs[-1]),
            "before_label": before_label, "after_label": after_label,
            "before_gate": before["verdict"] if before else None,
            "after_gate": after["verdict"] if after else None,
            "rows": rows}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="*", help="файлы логов (по умолчанию — скан .ray)")
    ap.add_argument("--out", default=HERE, help="куда писать battles.json/.js")
    ap.add_argument("--only-reward", action="store_true",
                    help="парсить только логи с разбором наград")
    a = ap.parse_args(argv)
    paths = a.logs or drop_untagged_dupes(sorted(sum((glob.glob(g) for g in DEFAULT_GLOBS), [])))
    obs_dir = os.path.join(a.out, "obs")          # sidecar-входы модели (дампер с --obs)
    battles, files = [], []
    tag_defaults = {}
    for p in paths:
        if not os.path.exists(p):
            print("пропущен (нет файла):", p)
            continue
        if p.endswith(".json"):                      # машиночитаемый дамп — без эвристик
            bs = parse_json_file(p, obs_dir=obs_dir)
        else:
            bs = parse_file(p, only_reward=a.only_reward)
        for bt in battles_iter_reward_tags(bs):
            for t in bt:
                tag_defaults.setdefault(t["name"], abs(t["w"]))
        if bs:
            files.append(os.path.basename(p))
            battles.extend(bs)
    for bt in battles:                              # legacy-логи/старые дампы без set -> учебные
        bt.setdefault("set", "chaos")
    gate = extract_gate()
    data = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": files, "tagDefaults": tag_defaults, "gate": gate,
            "roleStats": aggregate_roles(battles), "battles": battles}
    out_json = os.path.join(a.out, "battles.json")
    out_js = os.path.join(a.out, "battles.js")
    txt = json.dumps(data, ensure_ascii=False)
    open(out_json, "w", encoding="utf-8").write(txt)
    open(out_js, "w", encoding="utf-8").write("window.BATTLES_DATA=" + txt + ";\n")
    print("боёв: %d из %d файлов -> %s" % (len(battles), len(files), out_json))
    n_win = sum(1 for b in battles if b.get("set") == "winrate")
    print("  набор: chaos(учебные)=%d | winrate(канон)=%d" % (len(battles) - n_win, n_win))
    with_rw = sum(1 for b in battles if b["hasRewardLines"])
    with_tag = sum(1 for b in battles if b.get("hasTags"))
    print("с наградами по шагам: %d | с as-if тегами: %d" % (with_rw, with_tag))
    n_obs = len(glob.glob(os.path.join(obs_dir, "*_step*.json"))) if os.path.isdir(obs_dir) else 0
    print("sidecar obs (вход модели по клику): %d файлов -> %s" % (n_obs, obs_dir))
    if gate:
        print("гейт-таблица: %d строк (до=%s / после=%s) из %s"
              % (len(gate["rows"]), gate.get("before_gate"), gate.get("after_gate"), gate["log"]))
    return 0


def battles_iter_reward_tags(bs):
    return ([st["reward"]["tags"] for bt in bs for st in bt["steps"]
             if st.get("reward") and st["reward"].get("tags")])


if __name__ == "__main__":
    raise SystemExit(main())
