# arent/stage_gate.py — гарнитур приёмки curriculum-этапов (§7, §8, §9).
#
# Читает matchup-отчёт (team_matchup.json: rows с outcome/candidate_is_foes) и счётчики
# (tactics_counters.json), считает win/loss/draw + bootstrap CI + side-parity + follow_rate,
# выносит PASS/FAIL по gate-порогам раздела 4 и пишет stage{N}_gate.md.
#
# Ключевое: гарнитур не гоняет бои — он агрегирует УЖЕ собранные данные (matchup_sources +
# Counters.to_dict()), чтобы тесты (§7 test_stage_gate_harness) и CLI-скрипт имели ОДИН путь
# к gate-проверке. Детерминизм CI — из arent.paired.bootstrap_ci.
from __future__ import annotations

from typing import Any, Dict, List, Optional

from arent.paired import bootstrap_ci

Row = Dict[str, Any]

# --- outcome-rate helpers -----------------------------------------------------


def outcome_rate(rows: List[Row], outcome: str) -> float:
    """Доля строк с данным исходом (0..1); пустой rows -> 0."""
    if not rows:
        return 0.0
    return round(sum(1 for r in rows if r.get("outcome") == outcome) / len(rows), 4)


def win_loss_draw(rows: List[Row]) -> Dict[str, float]:
    """Все доли исходов КАНДИДАТА (win/loss/draw/mutual/open)."""
    return {o: outcome_rate(rows, o) for o in ("win", "loss", "draw", "mutual", "open")}


def ci_for_win(rows: List[Row], resamples: int = 1000, seed: int = 1234) -> Dict[str, Any]:
    """Bootstrap CI на win_rate кандидата (1=win, 0=иначе) по всем боям."""
    values = [1.0 if r.get("outcome") == "win" else 0.0 for r in rows]
    return bootstrap_ci(values, resamples=resamples, seed=seed)


def side_parity(rows: List[Row]) -> Dict[str, Any]:
    """Self-play паритет §0.1/§4.1: разность win_rate между сторонами (hero/foes)."""
    hero = [r for r in rows if not r.get("candidate_is_foes")]
    foes = [r for r in rows if r.get("candidate_is_foes")]
    wr_hero = outcome_rate(hero, "win")
    wr_foes = outcome_rate(foes, "win")
    diff = round(wr_hero - wr_foes, 4)
    return {"win_hero_side": wr_hero, "win_foes_side": wr_foes, "diff": diff,
            "n_hero": len(hero), "n_foes": len(foes)}


# --- gate-пороги и проверки ---------------------------------------------------

#: gate-спека по этапам (раздел 4); можно расширять/переопределять из JSON.
GATE_THRESHOLDS: Dict[str, Dict[str, Any]] = {
    "stage0": {
        "min_fights": 1,
        "counters_nonempty": True,
    },
    "stage1": {
        "min_fights": 30,
        "side_parity_max_diff": 0.10,      # self-play win_hero_side ≈ win_foes_side
        "min_win_vs_random": 0.30,          # не хуже random (нижняя граница §0.1)
        "follow_rate_min": {"no_idle": 0.90},
    },
    # ЭТАП 4: укрытия/узости + случайная расстановка. гейт cover_shoot follow_rate>=0.70,
    # win_rate vs учителя (greedy/battlecast) >=0.50 на >=30 боёв side-swap. hold_choke —
    # справочно (порога нет: на малом числе узостных шагов follow_rate часто N/A).
    "stage4": {
        "min_fights": 30,
        "min_win_vs_random": 0.50,
        "follow_rate_min": {"cover_shoot": 0.70},
    },
}


def check_gate(stage: str, rows: List[Row], counters: Optional[Dict[str, Any]] = None,
               thresholds: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Проверяет gate-спеку этапа по matchup rows + counters; возвращает {pass, checks:[...]}."""
    spec = thresholds or GATE_THRESHOLDS.get(stage)
    if spec is None:
        raise ValueError(f"Нет gate-спеки для этапа {stage!r} (расширь GATE_THRESHOLDS)")
    checks: List[Row] = []

    # 1. Минимальное число боёв (reproducibility §1.6)
    n = len(rows)
    min_f = int(spec.get("min_fights", 1))
    checks.append({"name": "min_fights", "value": n, "threshold": min_f, "ok": n >= min_f})

    # 2. Счётчики непустые (Gate 0)
    if spec.get("counters_nonempty"):
        steps = (counters or {}).get("steps", 0)
        checks.append({"name": "counters_nonempty", "value": steps, "threshold": 0,
                       "ok": steps > 0})

    # 3. Side-parity (self-play §0.1: win_hero - win_foes ≈ 0)
    max_diff = spec.get("side_parity_max_diff")
    if max_diff is not None:
        sp = side_parity(rows)
        checks.append({"name": "side_parity", "value": abs(sp["diff"]),
                       "threshold": max_diff, "ok": abs(sp["diff"]) <= max_diff,
                       "detail": sp})

    # 4. Минимальный win_rate (vs random или абсолютный)
    min_win = spec.get("min_win_vs_random")
    if min_win is not None:
        wr = outcome_rate(rows, "win")
        ci = ci_for_win(rows)
        checks.append({"name": "min_win_vs_random", "value": wr, "threshold": min_win,
                       "ok": wr >= min_win, "ci": ci})

    # 5. follow_rate по тегам
    fr_min = spec.get("follow_rate_min", {})
    if fr_min and counters:
        tactics_block = counters.get("tactics", {})
        for tag_key, threshold in fr_min.items():
            tag_data = tactics_block.get(tag_key, {})
            fr = tag_data.get("follow_rate")
            if fr is None:
                ok = False   # N/A = дефект гейта (§11.3: applicable==0 → gated_zero)
            else:
                ok = fr >= threshold
            checks.append({"name": f"follow_rate({tag_key})", "value": fr,
                           "threshold": threshold, "ok": ok})

    passed = all(c["ok"] for c in checks)
    return {"stage": stage, "pass": passed, "checks": checks,
            "n_fights": n, "win_loss_draw": win_loss_draw(rows)}


# --- markdown-отчёт ----------------------------------------------------------

def write_gate_md(stage: str, gate_result: Dict[str, Any], path: str) -> str:
    """Пишет stage{N}_gate.md (TOC+строки PASS/FAIL); возвращает path."""
    lines = [f"# Stage Gate — {stage}", ""]
    status = "PASS ✅" if gate_result["pass"] else "FAIL ❌"
    lines.append(f"**Итог:** {status}  ({gate_result['n_fights']} боёв)")
    lines.append("")
    lines.append("## Проверки")
    lines.append("")
    lines.append("| # | Проверка | Значение | Порог | Статус |")
    lines.append("|---|----------|----------|-------|--------|")
    for i, c in enumerate(gate_result["checks"], 1):
        mark = "✅" if c["ok"] else "❌"
        val = c["value"] if c["value"] is not None else "N/A"
        lines.append(f"| {i} | {c['name']} | {val} | {c['threshold']} | {mark} |")
    lines.append("")
    wld = gate_result.get("win_loss_draw", {})
    if wld:
        lines.append(f"**Исходы кандидата:** win {wld.get('win', 0)}, loss {wld.get('loss', 0)}, "
                     f"draw {wld.get('draw', 0)}, mutual {wld.get('mutual', 0)}, "
                     f"open {wld.get('open', 0)}")
    lines.append("")
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path
