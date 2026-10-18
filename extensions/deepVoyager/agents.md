# agents.md — deepVoyager

AI-подсистема модуля `biyk_ext`: управление NPC в бою через нейросеть (LRT/LLM-агент).
На ход NPC собирает данные о поле боя, отправляет промпт на локальный сервер
`http://localhost:9999`, парсит ответ вида `move/…`, `target/…`, `use/…`, `message/…`
и исполняет действия на canvas.

## TL;DR для агента
- Вход: `index.js → init()`, вызывается лоадером `biyk_ext/main.mjs` (расширение включается галкой в настройках модуля, регистрация в `registry.js`).
- Без запущенного сервера `localhost:9999` ход NPC падает с ошибкой fetch — `getAction()` не обёрнут в try/catch.
- План развития — в `todo.md` (server, TDD-расчёт путей своим кодом, очковая система, playground, долгосрочное планирование).
- Запуск сервера: `server\run_server.bat` — окно консоли видно (port 9999, конфиг `server/.env`,
  пакеты — только в `.venv`; вручную: `.venv\Scripts\python.exe server.py`).
- Остановка: Ctrl+C в окне или снятие процесса, слушающего 9999. NORMAL stop окно закрывает само
  (`timeout /t 2`), `pause` остаётся только при коде выхода ≥ 1 — чтобы успеть прочитать трейс краха.
- Тесты сервера (TDD): из `server/` — `.venv\Scripts\python.exe -m pytest tests`; собственный расчёт хода — `planner/` (шаг 4: перебор целей/маршрутов, очки, лимит 5 с), файл ≤200 строк.
- Пересобрать оглавление: `Select-String -Path agents.md -Pattern '^#{1,3} '` и обновить диапазоны строк ниже.

## Оглавление
| # | Раздел | Строки |
|---|--------|--------|
| 1 | [Архитектура и поток выполнения](#1-архитектура-и-поток-выполнения) | 31–52 |
| 2 | [Структура файлов](#2-структура-файлов) | 53–94 |
| 3 | [Контракт данных и формат действий](#3-контракт-данных-и-формат-действий) | 95–165 |
| 4 | [Внешние зависимости](#4-внешние-зависимости) | 166–178 |
| 5 | [Паттерны и особенности](#5-паттерны-и-особенности) | 179–196 |
| 6 | [Известные проблемы / долг](#6-известные-проблемы--долг) | 197–212 |

---

## 1. Архитектура и поток выполнения

Хуки `updateCombat` и `combatRound` → `combatTurn()` (только для GM, троттлинг 5 с):

1. **Фильтры**: нет текущего боевого токена / мёртв (`hp == 0`) / не `npc` / игра на паузе — выход.
2. **Сбор данных** (`utils/combat.js`, `utils/help.js`, `utils/tokenInfo.js`):
   позиция, скорость (шаги = speed/5), статус по HP, языки, disposition;
   видимые участники боя (прямая LOS + «расшаривание» видимости союзниками в радиусе 30 футов);
   группировка friends/enemies/neutrals; доступные действия (equipped weapon/equipment, spell, consumable) и feat-эффекты;
   `movement` — «роза движений»: сколько шагов в 8 направлениях до препятствия.
3. **Запрос к ИИ** (`actions/api.js → getAction()`): промпт строится `buildPrompt()`
   (обычный NPC) или `buildPromptBoss()` (disposition === -2), POST на `:9999/ask`,
   ответ парсится регуляркой `/(move|use|target|message)\/([^\n]+)$/gm` в `[{action, conf}]`.
4. **Исполнение** с лимитами за ход: `move = speed/5`, `use = 1`, `bonus = 1`, `target = 1`.
5. **Ветвление по disposition**:
   - `-2` (босс/DM-персонаж): исполняется только `target`, затем GM видит сырой ответ
     нейросети в Dialog-окне — ход вручную.
   - иначе: actions исполняются по кругу; при провале `move()` («ИИ затупила») —
     авто-фолбэк: поиск «Рывок» в инвентаре, запрос маршрута на `:9999/path`
     (`api.sendRequest(src, token)` с полным снимком сцены) и пошаговое движение по нему.
     В конце — `game.combat.nextTurn()`.

## 2. Структура файлов

```
deepVoyager/
├── index.js            # init(): хуки боя, combatTurn(), глобальный api-объект
├── todo.md             # роадмап из 7 шагов (сервер, TDD, очки, playground…)
├── actions/
│   ├── api.js          # getAction(): fetch :9999/ask, parseResponse()
│   ├── move.js         # move(token, {direction}) — 8 направлений, коллизии, заняты
│   ├── target.js       # target(token, {id}) — game.user.updateTokenTargets
│   ├── use.js          # use(token, {itemId|item}) — item.use(), fuzzy-ID
│   └── message.js      # sendMessage(): чат-сообщение от имени токена через Polyglot
├── utils/
│   ├── combat.js       # getCurrentTokenData, getVisibleCombatTokens (LOS 30ft share), groupTokensByDisposition
│   ├── help.js         # getStatus (по % HP), buildItemAction, buildWeapons, similarity (Левенштейн)
│   ├── prompt.js       # buildPrompt, buildPromptBoss — текст промптов для LLM
│   ├── tokenInfo.js    # getMovementRose — шаги до препятствия в 8 направлениях
│   ├── logger.js       # log.{info,warn,error} с префиксом [deepVoyager]
│   ├── messageBox.js   # addGMButton(): кнопка в трекере боя, gmNotes в localStorage
│   └── dm.js           # пустой файл-заглушка
└── server/             # Python-сервер (Flask), порт 9999 — порт функции прототипа DeepWeb (шаг 2 todo.md)
    ├── server.py       # /ask (LLM-действия), /path (расчёт пути), /plan (свой план хода, шаги 3–4)
    ├── run_server.bat  # запуск в видимой консоли; при нормальном останове окно закрывается само
    ├── requirements.txt# flask, flask-cors, websocket-client, python-dotenv (ставить только в .venv!)
    ├── requirements-dev.txt # pytest — тоже в .venv
    ├── .venv/          # виртуальное окружение (в git не попадает)
    ├── .env / .env.example # SERVER_PORT, CDP_PORT, BRAVE_PATH, DEEPSEEK_PROFILE_DIR, DEEPSEEK_USE_EXPERT
    ├── libs/quin.py    # SimplePathfinder (A*, 8 направлений, правило углов D&D 5e) из прототипа
    ├── planner/        # собственный расчёт хода вместо LLM (шаги 3–4), иерархия классов:
    │   ├── service.py  # PlannerService — точка входа /plan; три источника кандидатов, лимит 5 с
    │   ├── context.py  # BattleContext/Scene/Token/Wall — разбор payload, speed/weapons, hostile_targets()
    │   ├── action.py   # Action + фабрики; JS-контракт move/target/use/message, 8 направлений
    │   ├── geometry.py # клетки, векторы направлений, расстояние по прямой, within_reach (допуск 0.5 кл)
    │   ├── armament.py # Weapon + parse_weapons/best_attack: зоны уверенного/сомнительного попадания
    │   ├── strategy.py # StrategyEnumerator — quin-маршруты (цель × direct/los × атака), лениво
    │   ├── explore.py  # BruteForceExplorer (BFS по достижимым клеткам) + RandomExplorer
    │   ├── pathfinding.py # PathfindingService — адаптер над quin (find_path/path_to_target)
    │   └── scoring.py  # Scorer: сближение 1 очко/клетка, атака 30 (уверенная) / 15 (сомнительная)
    ├── tests/          # pytest-покрытие (117 тестов): геометрия, оружие, модель, перебор, очки, роуты, логи
    └── src/            # CDP-мост к DeepSeek через Brave: browser.py (пути/порт из env), page.py, deepseek.py, timer.py
```

## 3. Контракт данных и формат действий

**Объект `data` для промпта** (`index.js`, шаги 1–3):
`{ name, x, y, speed, step, baseMove, status, languages, disposition,
friends[], enemies[], neutrals[], availableActions[], availableFeats[], movement{} }`
— каждый токен: `{ id, name, disposition, x, y, weapon, ac, status }`;
каждое действие: `{ id, name, type, uses, maxUses, recharge, range, rangeAll, damage, description, … }`.

**Формат ответа LLM** (по строке на действие, комментарии с `//` игнорируются):
```
move/up|down|left|right|upleft|upright|downleft|downright
use/<itemId>            # совпадение по similarity > 0.87 (Левенштейн)
target/<token_id>
message/<язык>/<текст>
```

**Ответ `:9999/path`**: `{ path: [direction…] }` — последовательность направлений,
по которой токен идёт без размышлений LLM.

**Формат запроса на `/path`** (`api.getAllData()`):
`{ src, token, data: { scene: {id,name,width,height,gridSize}, npcs[], walls[] } }`,
где `npcs[]` — все токены с центром/размером/HP/disposition, `walls[]` — стены/двери/окна
с точками A/B и состояниями closed/locked, полями move/sight.

**Эндпоинт `/plan`** (шаги 3–4 плана): payload как у `/path` + необязательные
`speed` (футы за ход, по умолчанию 30) и `weapons` (массив вооружения из
`utils/help.js buildWeapons()`: `{id, name, damage, attackBonus, sureFt, doubtFt, ranged, properties}`;
`ranged` — дальнобойность (в JS: `actionType === 'rwak'`; на сервере при отсутствии поля
выводится как `doubtFt > sureFt`, поэтому старый клиент тоже получает правило «в упор»);
`properties` — коды свойств dnd5e (`thr` метательное, `rch` досягаемость, `fin`, `amm`, …),
в JS снимаются с `system.properties` (в 3.x это Set, в 2.x — объект `{код: true}`);
в массив попадают предметы, которыми можно атаковать как оружием, — `actionType`
`mwak`/`rwak` (оружие в руках и природное оружие NPC, оформленное как `feat`);
без оружия атака не планируется). Ответ `{"actions": [{action, conf}…]}` — форма совпадает
с parseResponse() для `/ask`, поэтому combatTurn() не требует правок JS.
Логика: три источника кандидатов (quin-маршруты StrategyEnumerator → полный BFS-перебор
достижимых за ход клеток BruteForceExplorer → случайные прогулки RandomExplorer), замена
только при `score > best`, поэтому победитель детерминирован; при превышении лимита 5 с
фиксируется лучший из уже рассмотренных. Из каждой клетки подбирается лучшая атака:
оружие и зона (уверенная 30 / сомнительная 15 очков) выбираются по максимуму очков,
поэтому «подойти ради уверенного удара» против «остаться и выстрелить сомнительно»
решает арифметика. Очки за сближение считаются вдоль прямой до ОПОРНОГО врага: цели
атаки (из `target`-действия), если атака в плане есть, иначе — до ближайшего
(`scoring.Scorer.breakdown` возвращает `ref_kind`/`ref_id`/`ref_name`/`weapon_name`).
Раньше прямая всегда мерилась до ближайшего, из-за чего подход к собственной цели не стоил
очков, пока рядом стоит кто-то другой, и «стоять и стрелять на пределе уверенной зоны»
было равно «подойти и ударить» (побеждал первый по порядку кандидат).
Выстрел дальнобойным оружием в упор (цель не дальше 5 футов =
соседняя клетка, включая диагональ) считается сомнительным и даёт 15 очков, а не 30
(`armament.MELEE_THREAT_CELLS`), поэтому планомерное сближение «до упора» невыгодно.
Исключение — метательное оружие (свойство `thr`): бросок вплотную идёт без помехи, оно
бьёт уверенно и в упор, и на своей дистанции (`armament.THROWN_PROPERTY`).
Вставать на клетку существа нельзя (последний шаг убирается).
Выстрел по дальней цели, когда кто-то стоит вплотную, — нормальное поведение: помеха
привязана к цели атаки, а не к наличию соседа (`armament.MELEE_THREAT_CELLS`).
Если врагов/ходов нет — `{"actions": []}`.
Логи: консоль (`[plan] итог: …`) плюс постоянный двойной журнал `server/logs/requests.jsonl`
(машиночитаемый) и `server/logs/requests.log` (читаемый) — полное «что пришло → что ответили».
Каждый обмен помечается коротким идентификатором события `#<8 hex>` (`uuid4().hex[:8]`):
он стоит во всех строках консоли этого запроса, в поле `event` записи jsonl и в заголовке
блока текстового лога (`=== [ts] POST /plan #a1b2c3d4 ===`). По строке из консоли достаточно
вытащить этот id и найти его в `server/logs/requests.jsonl` — там весь обмен целиком.
Строка `оружие:` подписывает каждый entry именем и id (`Праща JRgq…[1d4 + @mod,
30/120фт, дальноб]`, метки `дальноб`/`метат`), а `итог:` печатает `сближение A→B футов
(+N) к цели` (или `к ближайшему`, если атаки в плане нет) и `Оружие → «Имя токена» <id>` —
по одной строке видно, чем, в кого и с какого расстояния били (имена токенов в бою
повторяются, поэтому рядом всегда id).
Проверить решение по записанному обмену: `python biyk_ext/temp/replay_event.py <event id>`
(выбранный план + топ кандидатов с очками), `… replay_event.py scan` — пересчёт всех
плановых событий журнала по теперешним правилам (скипт в gitignore-`temp/`, не часть сервера).

## 4. Внешние зависимости

- **Сервер `http://localhost:9999`** — свой, в `server/` (Flask, Python 3.11 в `.venv`):
  эндпоинты `/ask` (LLM-действия через CDP-мост к chat.deepseek.com в Brave),
  `/path` (A* по сетке, `libs/quin.py`) и `/plan` (собственный расчёт, `planner/`: расчёт
  хода целиком, combatTurn() дёргает `/plan` первым, LLM — только фолбэк).
  Порт функции — прототип `C:\Users\b5\Desktop\DeepWeb` (шаг 2 плана).
  Профиль браузера с сессией DeepSeek переиспользуется из DeepWeb через `DEEPSEEK_PROFILE_DIR` в `.env`.
- **Модуль Polyglot** — для `message/…` (селектор `#polyglot select` для выбора языка).
- **Система dnd5e** — `actor.system.attributes.*`, `item.system.equipped/uses/…`, `item.use()`.
- **biyk_ext loader** (`main.mjs`, `registry.js`, `settings.mjs`) — включается настройкой `deepVoyager`;
  api-объект доступен как `game.modules.get("biyk_ext").api`.

## 5. Паттерны и особенности

- **Проверка коллизий — трёхуровневый fallback** (`move.js`, `tokenInfo.js`):
  `CONFIG.Canvas.polygonBackends.movement.testCollision` → `token.document.checkCollision` →
  `canvas.walls.checkCollision(Ray)`. Клетка считается занятой, если живой токен
  (hp > 0) пересекает bounding box — заходить нельзя, только обходить.
- **Троттлинг хода**: `COMBAT_TURN_THROTTLE = 5000` мс + `setTimeout(500)` в начале —
  защита от двойных срабатываний `updateCombat`/`combatRound`.
- **Disposition-гейты**: обычная группировка — друзья по равенству disposition;
  для `-2` друзья = disposition `-1` (ИИ-враги игроков). Для `use`-действия с «Рывок»
  лимит движения увеличивается на `baseMove`.
- **Инъекция приказа GM**: `localStorage.gmNotes` попадает в промпт блоком
  «ВАЖНО! ПРИКАЗ ОТ ГМ» — редактор кнопки в трекере боя (`messageBox.js`).
- **Опциональный debug-режим `move`**: `conf.debug === true` — лог расстояний
  до препятствия в пикселях по 8 направлениям (лучевое сканирование по 1 px).
- **Макрос-проверка пути**: `game.modules.get("biyk_ext").api.testPath()` —
  по 2 выбранным токенам (или токен+цель) ходит первым ко второму через `/path`.

## 6. Известные проблемы / долг

- `getAction()` без try/catch: сервер не запущен → необработанная ошибка в хуке, ход зависает.
- Очки за сближение не ограничены: план может побросать соседнего врага и бежать 6 клеток
  к дальнему (подход к своей цели плюс 8–9 очков) — при добавлении штрафа урона (todo шаг 5)
  стоит пересмотреть и «цену» дальнего погони.
- Лимиты в `combatTurn` прощают двойной `limit.move--` (шаг фолбэка + итоги после `move`) —
  при доработке аккуратно пересчитать семантику «шаги».
- `use.js`: `throw` с последующим недостижимым `return false`; `item.use()` работает только
  если предмет выбран/валиден для быстрый бросков — для части заклинаний могут требоваться цели.
- Регулярка `parseResponse` требует `$` в конце строки → действия, вклеенные в markdown-блок
  или с пробелами в конце, теряются; LLM может выдать несуществующие ID (частично лечится `similarity`).
- `getAllData()` собирает ВСЕ токены (`if (!isPlayerControlled || 1)` — второе условие always-true).
- `utils/dm.js` пустой; `init()` не снимает хуки при выключении расширения (reload=true).
- Промпты дублируют ~90% текста между `buildPrompt`/`buildPromptBoss` — при переносе расчёта
  пути на свой сервер (todo шаг 3) большая часть «move-инструкций» станет ненужной.
