# -*- mode: python ; coding: utf-8 -*-
# arent/arent.spec — сборка arent.exe (PyInstaller).
#
# Вход — main.py (он же cli), рядом кладутся config.json и снимки сцен. planner и
# playground берутся целиком: учитель разметки и арены генерации выборки живут там,
# и без них exe умеет только играть, а не учиться.
#
# Сборка: arent\build_exe.bat (нужен arent\.venv из setup.bat). Результат:
#   dist\arent\arent.exe + dist\arent\_internal\...   — папку переносимой делает то,
# что data\ и runs\ лежат РЯДОМ с exe (arent/paths.py при sys.frozen берёт каталог exe).
import os

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH задаёт PyInstaller (каталог spec-файла); без него работаем от текущего каталога,
# чтобы spec можно было запускать и вручную: pyinstaller arent\arent.spec
HERE = os.path.abspath(globals().get("SPECPATH") or ".")
SERVER = os.path.dirname(HERE)                 # учитель (planner) и арены (playground) живут выше
HIDDEN = (collect_submodules('planner') + collect_submodules('playground')
          + collect_submodules('libs') + collect_submodules('arent'))

DATAS = [(os.path.join(HERE, 'config.json'), 'arent')]
if os.path.isdir(os.path.join(HERE, 'data', 'payloads')):
    DATAS.append((os.path.join(HERE, 'data', 'payloads'), 'arent/data/payloads'))
# арены playground и points.json — это данные, а не модули: collect_submodules их не берёт,
# без них учитель размечал бы по DEFAULTS, а gen видел бы только живые снимки
DATAS.append((os.path.join(SERVER, 'playground', 'arenas'), 'playground/arenas'))
DATAS.append((os.path.join(SERVER, 'points.json'), '.'))

a = Analysis(
    [os.path.join(HERE, 'main.py')],
    pathex=[SERVER],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt5', 'PySide2', 'matplotlib', 'IPython', 'notebook',
              'pytest', 'setuptools'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='arent',
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='arent')
