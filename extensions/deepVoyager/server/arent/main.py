# arent/main.py — точка входа собранного exe (arent.exe) и ручного запуска скриптом.
#
# Без аргументов показывает окружение (info): запуск двойным щелчком не должен
# выглядеть как зависший чёрный экран. Параметры — те же, что у `python -m arent`.
import os
import sys

if __package__ in (None, ""):                       # запуск как python arent/main.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arent import paths                              # noqa: E402
from arent.cli import main                           # noqa: E402

if getattr(sys, "frozen", False) and not os.getenv("POINTS_FILE"):
    # в собранном exe коэффициенты учителя берутся из points.json рядом с ним,
    # а не из встроенной копии: правка файла видна на следующем запуске
    local = os.path.join(paths.workspace(), "points.json")
    if os.path.exists(local):
        os.environ["POINTS_FILE"] = local

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["info"]))
