# arent/__init__.py — обучение нейроагента хода NPC (шаг 6 todo.md).
#
# Пакет живёт внутри server/ и переиспользует планировщик как учителя:
#   observe  -> payload /plan в схему наблюдения v1 (spec.SCHEMA)
#   encode   -> наблюдение в векторы состояния и слотов действий
#   dataset  -> состояния арен + живых снимков, разметка PlannerService, .jsonl
#   net      -> политика (3 головы по слотам) + value, чистый python или torch
#   train    -> behavior cloning чекпойнтом в arent/runs/
#   play     -> модель -> список действий формата /plan
# Тяжёлые зависимости (torch) не обязательны: без него работает pure-python сеть,
# а если torch установлен и есть CUDA, обучение идёт на видеокарте (arent/backend.py).
