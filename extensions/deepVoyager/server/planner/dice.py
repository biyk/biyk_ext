# planner/dice.py — ожидание от записи кубика: «1d6+2» -> 5.5.
#
# Симуляция хода (пункт 5) не бросает кубики: она сравнивает варианты, а шум броска
# сделал бы сравнение несходным между запусками. Поэтому там, где нужен урон, стоит
# математическое ожидание — среднее кубика (n*(сторон+1)/2) плюс модификатор.
# Ссылки вида @mod/@prof/@res сервер не резолвит: это данные актёра, их в запросе нет
# (долг). Строка без кубика («5», «3 + 1») — просто постоянная; мусор — 0.
import re
from typing import Optional

#: один член «NdM±k»; модификатор не берём, если за ним сразу идёт ещё кубик («2d6+1d4»)
DICE_RE = re.compile(r"(\d*)d(\d+)(\s*[+-]\s*\d+(?!d))?", re.IGNORECASE)
#: строка целиком — только постоянные, иначе «1d» (битый кубик) сложится в «1»
CONST_RE = re.compile(r"^\s*[-+]?\d+(\s*[-+]\s*[-+]?\d+)*\s*$")
NUMBER_RE = re.compile(r"[-+]?\d+")


def average(text: Optional[str]) -> float:
    """Средний результат строки урона; 0.0 — если разбирать нечего («», «—», «удар»)."""
    raw = str(text if text is not None else "")
    total = 0.0
    found = False
    for term in DICE_RE.finditer(raw):
        found = True
        count = int(term.group(1) or 1)             # «d8» = один кубик
        sides = int(term.group(2))
        mod = term.group(3) or ""
        # «+ 2» -> «+2»: int() не переносит пробел между знаком и цифрами
        total += count * (sides + 1) / 2 + (int("".join(mod.split())) if mod else 0)
    if not found and CONST_RE.match(raw):
        total = sum(int(number) for number in NUMBER_RE.findall(raw))
    return max(0.0, total)                          # модификатор не уводит ожидание в минус
