# playground/__main__.py — запуск площадки: python -m playground --rounds 1,2,3 --timers 2,3,5
import sys

from playground.run import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
