# arent/__main__.py — `python -m arent gen|train|play|info`.
import sys

from arent.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
