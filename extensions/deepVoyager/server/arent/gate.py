# arent/gate.py — честный вердикт гейта против МИКСА учителей-эталонов (Фаза D / D3).
#
# Это ЧИСТАЯ функция (без Ray/симу/сети): вход — уже посчитанные по каждому сопернику меры
# исхода (win_rate, bootstrap-нижняя граница boot_lower, fights), выход — структурированный
# вердикт. Вынесено из .ray/ray_stage5_pipeline, чтобы (1) логика порога тестировалась без
# обучения, (2) пайплайн и любые будущие гейты делили ОДНО определение «прошёл/не прошёл».
#
# Определение PASS (по плану §D3 «не регрессить к лучшему и превзойти средний mix»):
#   модель проходит против ВСЕХ учителей микса, т.е. для КАЖДОГО учителя:
#     fights >= min_fights  И  win_rate >= win_thr  И  boot_lower >= boot_thr.
#   win_rate — доля побед кандидата в этом matchup; boot_lower — нижняя квантиль bootstrap-CI
#   (не полагаемся на среднее: шум не должен «продавать» перевес). Пороги win_thr/boot_thr=0.50
#   = «как минимум не хуже» каждого эталона с статистической уверенностью.
from typing import Any, Dict, Optional

GATE_WIN_THR = 0.50       # минимальная доля побед против каждого учителя
GATE_BOOT_LOWER = 0.50    # нижняя граница bootstrap-CI тоже обязана быть >= этого
GATE_MIN_FIGHTS = 30      # меньше — вердикт статистически не обеспечен, не PASS


def gate_verdict(metrics: Dict[str, Dict[str, Any]], *, win_thr: float = GATE_WIN_THR,
                 boot_thr: float = GATE_BOOT_LOWER,
                 min_fights: int = GATE_MIN_FIGHTS) -> Dict[str, Any]:
    """Вердикт гейта по {имя_учителя -> {win_rate, boot_lower, fights}}.

    Возвращает плоский отчёт: passed (bool), teachers (сортированный список имён),
    per_teacher {name: {..., passed, reason}}, worst_win_rate (минимум win_rate по всем или
    None при пустом входе), failed (учителя, где win/boot не прошли), insufficient (где
    боёв меньше min_fights). Функция чистая: вход не мутируется, одинаковый вход -> одинаковый
    выход (детерминировано, включая порядок списков — по имени).
    """
    per_teacher: Dict[str, Dict[str, Any]] = {}
    failed, insufficient = [], []
    worst: Optional[float] = None
    for name in sorted(metrics):
        m = metrics[name]
        win = float(m.get("win_rate", 0.0))
        boot = float(m.get("boot_lower", 0.0))
        fights = int(m.get("fights", 0))
        reasons = []
        if fights < min_fights:
            reasons.append("insufficient_fights")
            insufficient.append(name)
        if win < win_thr or boot < boot_thr:
            reasons.append("below_threshold")
            failed.append(name)
        passed = not reasons
        per_teacher[name] = {"win_rate": round(win, 4), "boot_lower": round(boot, 4),
                             "fights": fights, "passed": passed, "reason": reasons}
        worst = win if worst is None else min(worst, win)
    return {
        "passed": bool(metrics) and not failed and not insufficient,
        "teachers": sorted(metrics),
        "per_teacher": per_teacher,
        "worst_win_rate": worst,
        "failed": failed,
        "insufficient": insufficient,
        "thresholds": {"win_thr": win_thr, "boot_thr": boot_thr, "min_fights": min_fights},
    }
