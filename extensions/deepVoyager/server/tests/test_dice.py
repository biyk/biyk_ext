# tests/test_dice.py — парсер кубиков: сколько урона ждать от строки вида «1d6+2».
#
# Симуляция хода (пункт 5) оперирует ожиданием, а не броском: бросок — это шум,
# а решение «идти в угрозу или нет» должно быть детерминированным.
from planner.dice import average


def test_plain_dice():
    assert average("1d4") == 2.5
    assert average("d8") == 4.5              # «d8» = один кубик
    assert average("2d6") == 7.0
    assert average("2D6") == 7.0             # регистр не важен


def test_numeric_modifier():
    assert average("1d6+2") == 5.5
    assert average("1d4 + 2") == 4.5         # пробелы вокруг знака
    assert average("1d8-1") == 3.5
    assert average("2d10+5") == 16.0


def test_several_dice_terms():
    assert average("2d6+1d4") == 9.5         # 7.0 + 2.5, «+1» не съедает следующий кубик
    assert average("1d8 + 1d4") == 7.0       # 4.5 + 2.5
    assert average("1d6+2+1d4") == 8.0       # модификатор числами, затем ещё кубик


def test_unresolved_modifiers_are_ignored():
    # @mod/@prof сервер не резолвит (это данные актёра) — считаем только кубик
    assert average("1d4 + @mod") == 2.5
    assert average("2d6[+5]") == 7.0         # скобки-подсказки тоже не ломают разбор


def test_constant_without_dice():
    assert average("5") == 5.0
    assert average("3 + 1") == 4.0


def test_garbage_is_zero():
    for text in ("", " ", "—", "-", "удар", "нет", "1d", "abc"):
        assert average(text) == 0.0


def test_average_never_negative():
    assert average("1d4-10") == 0.0          # модификатор не уводит ожидание в минус
