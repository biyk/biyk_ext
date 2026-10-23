# AGENTS.md — глубокое ориентирование для агентов в этом репозитории

Каталог: `extensions/deepVoyager/server`. Это сервер тактического ИИ для ходов NPC в
FoundryVTT (система dnd5e) плюс обучаемый нейроагент тех же ходов. Ниже — что проект
умеет, как он устроен, как запускать, какие правила разработки обязательны и какие
ловушки уже наступали.

## 1. Что это и зачем

Две взаимодополняющие подсистемы живут в одном дереве:

- **Планировщик-учитель** (`planner/`) — детерминированный перебор вариантов хода
  (маршруты по сетке, выбор цели и оружия, прицеливание, укрытия, угрозы). Отвечает
  за эндпоинт `/plan`: по боевому состоянию возвращает список легальных действий.
  Его коэффициенты — в `points.json` (горячая перезагрузка, менять можно без рестарта).
- **Нейроагент** (`arent/`) — политика, которая учится *подражать* планировщику и
  бить его по честным гейтам. Pipeline: датасет → behavior cloning → (DAgger / PPO)
  → оценка матчапами. Схема действий эволюционировала: schema 2 (три головы: клетка /
  цель / оружие) → schema 3 (move-plan: план/цель/оружие совместным декодом).

Текущее состояние Этапа 3: **PPO убран** (4 прогона подряд деградировал BC-посев),
используется **итеративный on-policy DAgger** — текущая политика играет, сильнейший в
роли учитель (`battlecast`) размечает посещённые состояния, датасет растёт, BC
переобучается. Пороги гейтов (§4.0) **никогда не двигаются ради «зелёки»**.

## 2. Карта каталога

| путь | назначение |
|---|---|
| `server.py` | Flask: `/ask` (LLM, по умолчанию выключён), `/path` (quin-путёвка), `/plan` (планировщик + capture) |
| `planner/` | планировщик-учитель: `context.py` (BattleContext), `initiative.py`, `service.py`, `scoring.py`, `points.py`, `pathfinding.py`, `los.py`, `lookahead.py` |
| `playground/` | арены и генерация боёв: `arena.py` (`build_payload`), `run.py` |
| `arent/` | пакет нейроагента (см. §3) |
| `arent/runs/<имя>/` | чекпойнты прогонов: `model.json`, `model_best.json`, `history.json`, `summary.json` |
| `arent/data/` | `samples/*.jsonl` (выборки) и `payloads/` (живые снимки, `captures/`) |
| `.ray/` | Ray-GPU конвейер: скрипты `ray_stage*.py`, лаунчеры `launch_*.ps1`, пробы/Smoke `_*.py` |
| `tests/` | pytest-набор (~81 файл `test_*.py`, ~880 тестов) |
| `points.json` | тюнинг планировщика-учителя (горячая перезагрузка) |
| `logs/` | журнал запросов/ответов `requests.jsonl` / `requests.log` |
| `.env` | настройки сервера (порт, флаги DeepSeek) |

### Ядро `arent/` (самое частое)

| файл | за что отвечает |
|---|---|
| `spec.py` / `spec3.py` | схемы наблюдения/действия (SCHEMA=2 / 3), `dims()` |
| `net.py`, `torch_net.py`, `pure_net.py`, `backend.py` | сеть и бэкенды (torch / pure-python) |
| `dataset.py` | генерация выборки; `sample_from_labeled_v3` (ctx-ядро), `state_key` (дедуп) |
| `teachers.py`, `battlecast.py`, `teacher.py`, `teacher_select.py` | учителя и выбор «сильнейшего в роли» |
| `dagger.py` | on-policy rollout → разметка посещённых ctx → агрегация (`aggregate()`) |
| `env.py`, `polyenv.py` | Gym-подобные окружения боя (`PolyFightEnv._observe`, `step`) |
| `tactics_*.py` | shaping наград (детект тактик, `distance_field_value`, шейпер, контекст) |
| `train.py`, `rl.py`, `torch_rl.py` | обучка BC и RL (тёплый старт, `_warm_params`) |
| `team_eval.py`, `evaluate.py`, `stage_gate.py` | оценка матчапами, гейты |
| `paths.py` | разрешение `run-name → путь model.json` |
| `cli.py`, `main.py`, `arent.bat` | CLI: `gen / train / bench / play / info` |

## 3. Окружения (ВАЖНО: изолированы, не смешивать)

Три отдельных venv, каждый под свою задачу. **Ничего не ставим глобально.**

| venv | для чего | как |
|---|---|---|
| `server/.venv` | Flask-сервер, тесты API (`python-dotenv`) | `.venv\Scripts\python.exe` |
| `arent/.venv` | обучение/тесты ядра (torch + pytest) | `arent\.venv\Scripts\python.exe` |
| `.ray/.venv` | Ray-клиент (py 3.10.11) для прогонов на кластере | `.ray\.venv\Scripts\python.exe` |

Кластер: head `192.168.2.107`, Ray client порт `10001`, GPU RTX 4060, Ray 2.59.0
(head на py 3.10.22 — несоответствие патч-версии даёт предупреждение, работает).

## 4. Как запускать

Сервер:
```
run_server.bat            # либо: .venv\Scripts\python.exe server.py  (порт из .env, default 9999)
```

CLI агента (из `arent/`):
```
arent gen --count 400 [--seed 7] [--arena NAME] [--append]
arent train [--dataset bc] [--name latest] [--epochs 40] [--kind auto|torch|pure]
            [--device auto|cuda|cpu] [--warm CKPT] [--val BC] [--keep-best]
arent bench [--epochs 5] [--kinds pure torch] [--devices cpu cuda]
arent play [--model latest] [--arena NAME | --payload file.json] [--out result.json]
arent info
```
Формат чекпойнта общий (JSON) — модель с 4060 играется где угодно, даже без torch
(pure-python бэкенд). `--warm` продолжает веса, но НЕ оптимизатор; скрытие/размеры
обязаны совпасть, кросс-схема (schema 2 ↔ 3) отвергается `_warm_params`.

Ray-GPU прогон (Stage 3 DAgger):
```
.ray\launch_s3dagger.ps1   # BC-v3 посев (с нуля) -> K раундов DAgger -> два честных гейта
                             # лог: .ray\stage3_dagger1.log
```
Перед полным прогоном на GPU — **всегда CPU-Smoke** (`.ray\_smoke_*.py`), чтобы
проверить логику сидов/раундов/цепочки warm дёшево.

## 5. Как тестировать (TDD обязателен)

RED → GREEN: сначала падающий тест на желаемое поведение, потом минимальная реализация.
Каждый тест — атомарный. Перед завершением — полный регресс.

```
# ядро arent (нужен torch-интерпретатор):
arent\.venv\Scripts\python.exe -m pytest tests -q
# тесты сервера идут через server/.venv (dotenv)
```
Тесты сервера (`tests/test_server_log.py`, `tests/test_server_routes.py`) требуют
`server/.venv`; при прогоне ядра их можно исключить `--ignore`. Тест паритета
градиентов pure↔torch пропускается без torch.

Регресс этой машины: **~880 passed** после Stage-3 правок. GetProblems должен быть чист.

## 6. Оценка и гейты (§4.0)

Модель считается готовой только по честным матч-ап гейтам: `vs random`, `vs greedy`,
`vs battlecast` на stage3-пуле, с разменом сторон и sentinel-статистикой
(win_rate, bootstrap CI нижней границы, hero/foe, open first/second, per-pair).
Пороги зафиксированы (`GATE_VS_RANDOM=0.55`, `GATE_VS_TEACHER=0.50`,
`GATE_BOOT_LOWER=0.50`) и **не сдвигаются**, чтобы прогон «прошёл». Провал — это
валидный результат — репортим как есть, с разбором слабых сцен.

## 7. Ключевые факты о дизайне

- **Наблюдение** — фиксированный вектор (`me/weapons/enemies/allies/others/grid`,
  патч 11×11). Действия замаскированы над слотами → ответ всегда декодируется в
  легальный план.
- **Reward = base + potential + tactical**; разложение в `reward_breakdown` шага;
  `render_battle_trace` помечает «ВРЕДНО: не атакует, но получает +тактический».
- **Вредные награды запрещены**: shaping платит бонус за удержание дистанции / kite
  **только в ходах с атакой** (`distance_field_value` гейтится `c.attacked`); иначе 0,
  штраф за слишком близкое расстояние остаётся. Это закрывает эксплойт «пятиться без
  выстрелов и получать награду».
- **Схема 3** требует `cfg.schema = spec3.SCHEMA`; `feat_version=2`, `cell_feat=21`.
  `dims.state` НЕ различает schema 2/3 — смотреть `dims.schema`.

## 8. Известные ловушки (не наступать повторно)

- **PowerShell-обёртка** глотит кавычки и операторы: `python -c "..."` и `$x = ...`
  внутри `-Command` ломаются; `&&` не поддерживается (используйте `;` или `git -C`).
  Внутренний `|` в `Select-String -Pattern "a|b"` режется как конвейер. Решение: писать
  `.py`/`.ps1` файлы и запускать их; для «хвоста» — `Get-Content -Tail N`.
- **Ray Client Windows→head**: из remote-task наружу — **ОДИН** `model_text` (~1.16 МБ).
  Два больших возврата в одном объекте роняют клиент («Client is shutting down»).
  Растущий датасет держим ВНУТРИ GPU-task. ФС head **не переживает** отдельные remote-task
  (`runs/` исключён из working_dir) → каждая задача пересобирает веса из текстового аргумента.
  `Log channel is reconnecting` посреди прогона — нормально; перфолог буферится на head.
- **Артефакты не коммитим**: `data/samples`, `runs/`, `.venv`, `build/`, `dist`, логи —
  в `.gitignore`; smoke-выход чистим (`DeleteFile` по файлам, не shell `rm`).
- Никогда не печатать `auth_token`; не рестартить Ray head; не трогать чужие FoundryVTT
  модули за пределами `deepVoyager/`.

## 9. Что агент должен и чего не должен

**Должен:** держать ответы/доки на русском; идти TDD; перед GPU- прогоном делать
CPU-Smoke; оценивать честно по §4.0; оставлять `git status` чистым от мусора.

**Не должен:** двигать пороги гейтов ради PASS; коммитить без явной просьбы; ставить
пакеты глобально; смешивать venv; выдумывать механику фич — сверяться с правилами dnd5e
и реальным кодом.

## 10. Куда смотреть дальше

- `arent/README.md` — история и замеры CLI-конвейера (часть цифр из эпохи schema 2).
- `teaching_plan.md` — план обучения.
- `.ray/ray_stage3_dagger.py` — текущий Stage-3 DAgger-конвейер и гейты.
- `stage9_out/stage9_report.md` — пример формата отчёта оценки.
