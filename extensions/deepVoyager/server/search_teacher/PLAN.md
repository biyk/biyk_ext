# План: внешние учителя тактики и усиление текущих — чтобы наша модель становилась сильнее

> Вход: `deep.md` и `cgpt.md` (результаты двух агентов). Это единый план/дорожная карта:
> (1) изучение всех представленных вариантов, (2) подготовка к СОЗДАНИЮ новых учителей-противников,
> (3) УЛУЧШЕНИЕ тактик текущих учителей — всё под усиление обучаемой модели (схема v5: головы
> move/target/weapon/maneuver, бои 1-на-4 … 4-на-4).

## 🧭 Статус фаз (обновляется по мере прохождения)
Легенда: ✅ пройдено · 🔄 идём сейчас · ⬜ не начато.

| Фаза | Что | Статус | Артефакт/DoD |
|---|---|:-:|---|
| **0** | Верификация источников (пригодность учителей) | ✅ | `search_teacher/PHASE0.md` (web-первичка, лицензии/силы подтверждены) |
| **A** | Инфраструктура измерений (реестр политик + метрики `abset.py` + бенчмарк) | ✅ | A1+A2+A3 готовы; артефакт `bench/baseline_vs_ja2.json` (canon 72 + pool 180 сцен, fingerprint стабилен) |
| **B** | Усиление battlecast (evaluate_plan/focus-fire/позиция/heatmaps/roleplayer) | ✅ | B1 `battlecast_v2` (развязка по исходу сима + манёвр) — артефакт `bench/battlecast_v2_vs_base.json`; B2–B5 измерены и сознательно не внедрены (сведено к B1/переобучение/нет механики) |
| **C** | Новые учителя-стили (ufo_style/wesnoth_focusfire/ja2_positioning/cdda_ranged_support) | ✅ | `ufo_style`/`cdda_ranged_support` добавлены поведенчески-отличными (+ `ja2_positioning` из A); diversity-гонка `bench/phase_c_styles.json`: все играют, ни один не сломан. `wesnoth_focusfire` честно отсрочен (полиакторный уровень = D). ДоD C закрыт: разнообразие реально, метрики покрывают |
| **D** | Встраивание в обучение (BC-мультиучитель, оппонент-микс PPO, гейт-mix, куррикулум) | ✅ | Plumbing+local ✅: реестр generic (стили служат BC-демо/PPO-оппонентом без правок ядра — `test_arent_ext_styles_training` 16✅), честный гейт-mix `arent/gate.py` (`test_arent_gate` 6✅), wiring `.ray/ray_stage5_pipeline.py` (D1–D3 env-миксы), fix `_fan` (int-приведение). **Кластерный прогон (10.11.2026): BC+PPO-гейт против всех 5 учителей — PASS** (worst_win=0.6204); BC без PPO — FAIL на `cdda_ranged_support` (0.4907). **D4 куррикулум реализован в ядре** (`RlConfig.curriculum` + `parse_curriculum`/`curriculum_opponents`, `test_arent_curriculum` 9✅) — ждёт кластерного staged-замера. Подробно §D, лог `.ray/stage5_cluster_resume.log` |

> **Ключевые поправки Ф0 к этому плану:** (1) `roleplayer` подтверждён **MIT** и реально содержит
> готовый D&D-ИИ (focus-fire/expected-damage/лечение/Dash) → добавлен в B5 и как BC-демо-учитель;
> (2) `OpenCombatEngine` подтверждён **базовым** (ADR 0002/0003) → остаётся справочником, не учителем;
> (3) `Brogue CE = AGPL-3.0` (не permissive) → heatmap реализуем независимо.
> Подробности: `PHASE0.md`.

---

## 0. Решения, снятые с кода (чтобы план был исполним «в натуре»)

- **Учитель** = `TeacherPolicy` в `arent/teachers.py`: реализует `label(payload)`/`label_ctx(ctx)`/
  `plan(ctx)`/`pick(ctx)` -> `Labeled`, регистрируется декоратором `@register("имя")` и импортируется
  в `_autoload()`. Один класс — и он доступен ВЕЗДЕ: демо BC, оппонент `duel_opponents`, соперник гейта,
  closed-loop A/B.
- **Противник в бою** строится в `team_eval.build_controller`: строка `"battlecast"/"greedy"` ->
  `TeacherController`; `"random"` -> `RandomController`; объект сети -> `ModelController`. Новый
  учитель-противник подключается РЕЕСТРОМ, без правок боевого контура.
- **A/B-замер учителей** уже есть: `arent/abset.py` (`run(teachers=(...), rounds, seed, ci_seed)`).
- **Текущий сильнейший учитель** = battlecast (`arent/battlecast.py` + `arent/battlecast_heuristics.py`,
  порт battlecast-engine MIT). Награды/тактики — `points.json` секция `tactics` (единственное место, hot-reload).
- **Манёвры v5** (Dash/Disengage/Dodge) — самая молодая и слабая голова; её усиливать эвристиками
  «риск OA / ценность дистанции / ожидаемая защита».
- **Гейт сейчас** — только vs battlecast (`duel_opponents=("battlecast",)`). Второй сильный учитель
  позволит смешивать оппонентов в отборе PPO, гейте и демо BC.

**Reconciled вывод двух отчётов:** ни один внешний ИИ не доказан как «побеждает battlecast» по win-rate;
ценность — конкретные тактические ФУНКЦИИ. Стратегия: НЕ заменять battlecast, а **усилить battlecast
принципами извне + добавить 2–3 независимых стиля-противника**. №1-источник — UFO `evaluate_plan` +
D&D-эвристики roleplayer. OpenCombatEngine — только референс архитектуры (его «продвинутый» Tier 2/3
по собственному ADR 0002 базовый; из-за этого `deep.md`-рейтинг понижен).

---

## 1. Матрица всех вариантов (объединённая, с лицензионным вердиктом)

Легенда: **Порт**=1..5 (лёгкость независимой реализации под наши 4 головы); **Ман**=1..5 (покрытие
Dash/Disengage/Dodge/укрытий); **Учит**=1..5 (ценность как сильный противник); **Код?** = можно ли
копировать код (MIT/OGL — да с notice; GPL/CC-BY-SA/закрытый — только ИДЕИ).

| Источник | Домен | Порт | Ман | Учит | Код? | Какие головы обогащаем | Приоритет |
|---|---|:-:|:-:|:-:|:--|---|:-:|
| **UFO: Alien Invasion** (`g_ai.cpp`, `AI_FighterCalcActionScore`) | TBT-сетка, TU | 4 | 3 | 4.5 | идеи (GPL-2.0+) | `evaluate_plan` позиция→цель→оружие→манёвр→укрытие; штрафы опасной позиции и OA | **P1** |
| **Battle for Wesnoth** (RCA AI, `attack.cpp`, `ai.get_attacks()`) | гекс-тактика | 4 | 3 | 4.5 | идеи (GPL-2.0+) | командный `team_target_score`: focus-fire по комбинации; kill-chance/avg-losses; retreat/лечение как действие | **P1** |
| **Jagged Alliance 2 v1.13** (`DecideAction.cpp`, docs) | squad TBT | 3 | 5 | 4.5 | идеи (лицензия не подтверждена) | `move`/`maneuver`: фланги, укрытие с мин.-угрозой, подавление, отход при HP, friendly-fire | **P2** |
| **roleplayer** (PyPI, `data_battle.py`) | D&D 5e | 5 | 3 | 4 | проверить LICENSE | target=min-HP/nearest/wounded по WIS; expected-damage по INT; spell-slot-экономика | **P1** |
| **Brogue — Dijkstra Maps** | roguelike | 5 | 4 | 4 | permissive (проверить) | heatmap поля: kiting/retreat/cover-seeking детерминированно (`move`+`maneuver`) | **P2** |
| **OpenXcom AI** (`AIModule`/Xilmi) | XCOM-подобный | 3 | 5 | 4 | идеи (GPL-3.0) | phase-based scoring (атака→scout→cover); spotted/unspotted; aggression→cover | **P2** |
| **MegaMek Princess** (`FireControl`/`EnemyTracker`/`BehaviorSettings`) | BattleTech-гекс | 3 | 4 | 4 | идеи (GPLv3 + CC BY-NC-SA данные!) | угроза, дистанция, выбор оружия, взаимная поддержка, удержание/отход | P3 |
| **Cataclysm: DDA** NPC AI | grid-survival | 3 | 4 | 3.5 | идеи (CC BY-SA 3.0) | раздельно `repositioning` vs `fleeing`; preferred-range; поддержка стрелков | P3 |
| **Battle Brothers** (dev-блоги) | TBT-RPG | 3 | 3 | 4 | закрытый код | utility-профили архетипов (щит/засада/hit-run); AP-aware ожидание | P3 |
| **DnD5e-CombatSimulator** (`world.py`/`behavior.py`) | D&D 5e, Python | 5 | 2 | 3 | проверить | чистый Python pathfinding/formation на 2D-сетке | P3 |
| **Smart Combat NPC** (Foundry) | D&D 5e | 2 | 4 | 3.5 | закрытый коммерч. | КАТАЛОГ D&D-поведений (фланг/AoE/лечение/отход), не код | справочник |
| **OpenCombatEngine** (C#, ADR 0002) | D&D SRD | 5 | 2 | 2 | MIT код + OGL | референс архитектуры открытого D&D-движка; сам AI базовый | справочник |
| **dnd-rl / dnd-ml** | D&D 5e | 1 | 2 | 2.5 | LICENSE нет | ориентир механик/тестов (OA-aware path, concentration, слоты) | справочник |
| **mookAI** (Foundry) | D&D 5e | 4 | 1 | 2 | MIT | vision→target→path→approach→attack (для простых mook-юнитов) | низкий |
| **Warbringers.py** | wargame+MCTS | 4 | 4 | 3 | проверить | сравнение AI-стратегий; rollout-эвристики (MCTS — чёрный ящик) | низкий |
| **TurnBasedEngine** (samsmithnz) | XCOM-подобный C# | 4 | 3 | 2.5 | проверить | cover high/low/destruction каркас | низкий |
| **Tactical Troops (paper)** | squad, Utility+MCTS | 3 | 4 | 3 | только статья | utility-скоринг высокого уровня (дизайн-референс) | низкий |
| **Jagged Alliance 2 (оригинал)** | squad | 2 | 5 | 3 | SFI-SCLA (не OSI) | только названия действий (FLANK/TAKE_COVER/SEEK) — юрид. риск | ❌ не копировать |

**Отброшено как учителя:** `foundry-vtt-dnd-combat-ai` (LLM, недетерминирован), `For The King` (закрыт),
Freeciv/0 A.D. (RTS-макро, не TBT-микро), чисто шахматные/го-движки.

### 1.1 ⚖️ Уточнения после Фазы 0 (первичная web-проверка)
- **roleplayer** → **MIT-код + CC-BY-4.0(SRD)**, реальный пошаговый бой и inspectable AI;
  годится в `target`/`weapon`/`maneuver(dash,heal)`, НО бой абстрактный (нет grid/cover/OA). → P1.
- **OpenCombatEngine** → **MIT**, ИИ **базовый** (ADR 0002: finisher+flee<30%; ADR 0003: только Artillery
  kiting). Ценность = ADR-картотека D&D-правил (AStar/flank/OA/concentration/AoE). → справочник.
- **UFO** → **GPL-2.0**; **OpenXcom** → **GPL-3.0**; **JA2/Stracciatella** → **SFI-SCLA (не OSI)**;
  **Brogue CE** → **AGPL-3.0** (поправка: не permissive). Все — **только идеи**, код не копируем.
- Конфликт агентов по №1 разрешён: UFO(план)+Wesnoth(фокус)+JA2(позиция) как принципы + roleplayer (MIT).

---

## 2. Дорожная карта (фазы; каждая = «красный→зелёный» тест + чекпойнт)

### Фаза 0 — Верификация источников ✅ (ПРОЙДЕНА)
- Цель: собрать данные по каждому кандидату (лицензия/наличие кода/сила тактики/пригодность под 4 головы).
- Сделано: web-заход в первичные источники, снимок вердиктов → `PHASE0.md`; приоритеты подтверждены/поправлены.
- DoD 0: ✅ сняты пометки «проверить LICENSE» у P1-кандидатов; разрешён конфликт #1; план доработан (§1.1).

### Фаза A — Инфраструктура измерений ✅ (A1+A2+A3 готовы)
- **A1.** ✅ Реестр внешних политик для бенчмарка — `arent/ext_teachers.py` через `@register`, подключён
  в `teachers._autoload()`. Готовы: `battlecast_baseline` (честный алиас — неизменная базовая колонка A/B)
  и `ja2_positioning` (осторожный позиционный профиль: `threat=1.6` + `ManeuverWeights` с высокими
  Disengage/Dodge). `BattlecastTeacher.__init__` расширен параметрами `threat`/`maneuver_weights`
  (по умолчанию = прежнее поведение battleкаст, регресс зелёный). Остальные стили (`ufo_style`,
  `wesnoth_focusfire`, `cdda_ranged_support`) per PHASE0 — это НОВОЕ поведение, перенесены в Фазу C.
- **A2.** ✅ Расширены метрики `abset.py`: `METRICS` += `actions/kill/wasted`; `_agg` выдаёт производные
  `dmg_per_action`, `kill_rate`, `wasted_rate`, `mean_rollout`; `compare.fight` считает `actions_total`,
  `wasted` (холостой раунд), `kills`. Честно: OA received/prevented, cover-usage, focus-fire-rate,
  resource-efficiency из cgpt §6 появятся вместе с соответствующим поведением в B/C (пока считаем то,
  что реально измеряемо в текущем симе).
- **A3.** ✅ Бенчмарк-гонка `arent/teacher_bench.py` (`python -m arent.teacher_bench`): прогоняет
  выбранных учителей на `stage43_canon` (честная линейка) и `stage43_pool` (обучающий) на одном
  seed/бюджете, парный bootstrap CI, пишет `search_teacher/bench/baseline_vs_ja2.json`.
  `abset.build_set/run` получили `source`/`cap` (по умолчанию прежнее поведение).
  Честный вердикт первой гонки (baseline − ja2): осторожный профиль **слабее** baseline по
  cleared/survived/kills/dmg_net (CI не накрывает 0), а raw rollout — в пределах шума (CI накрывает 0).
  Это НЕ заявление «учитель сильнее» — Фаза A лишь доказала, что harness различает профили.
- **Прогон тестов (arent-venv):** целевые `test_arent_teachers`/`test_arent_abset`/`test_arent_teacher_bench`
  зелёные; `test_arent_battlecast`(+maneuvers) без регресса. Полный `tests/` = 1091 passed, 3 failed —
  падение в `test_tactics_config` из-за tuning'а `points.json` (shaping-теги включены), к Phase A не относится.
- **DoD A:** ✅ таблица «учитель vs battlecast» по всем метрикам (summary гонки); воспроизводимость
  (стабильный fingerprint набора при одном seed/cap); harness-багов не найдено.

### Фаза B — Усиление СОБСТВЕННОГО battlecast 🔄 (макс. рычаг, нулевой лицензионный риск)
Ничего не копируем — переписываем принципы.
- **B1. Совместная оценка плана (`evaluate_plan`, из UFO).** ✅ РЕАЛИЗОВАНО как `arent/battlecast_v2.py`
  (`@register("battlecast_v2")`, ПОДКЛАСС базового battlecast — сам `battlecast.py` НЕ тронут, реестр
  `battlecast` не подменён, регресс v2/3/4/5 зелёный). Идея UFO «оценивать план ЦЕЛИКОМ исходом, а не
  линейной свёрткой голов» перенесена честно: тот же набор кандидатов, что перебирает база (атака по
  достижимым клеткам + линия каждого манёвра), но РАЗВЯЗка выбирает линию по `planner.turns.rollout`
  (исход НАШЕЙ симуляции: мёртвый враг перестаёт бить, стояние в нескольких melee-зонах складывается),
  со строгим порогом `margin` (переключаемся с базового выбора только с запасом; `margin=+inf` →
  побитово базовый battlecast — якорь в тестах). Дефолт: `horizon=2, margin=0, top=6`.
  ⚠️ Исправлена ошибка прототипа: первый Rollout/Margin-прототип терял Уклонение/Отступление (переопределял
  `plan()` без линии манёвра) и потому регрессил на пуле — v2 включает манёвр в кандидаты, и регресс ушёл.
  **Честный замер** (парный bootstrap CI, `bench/battlecast_v2_vs_base.json`, разность = battlecast − v2,
  `*` = CI не накрывает 0): canon(36) rollout **−76.1\***, survived **−0.250\*** (v2 0.50 vs 0.25), cleared
  +0.028 (CI накрывает 0 — реального проигрыша нет); pool(48) rollout **−54.0\***, survived **−0.146\***
  (v2 0.292 vs 0.146), dmg_net −1.95\* (небольшая честная плата за осторожность). Вывод: v2 устойчиво и
  значимо сильнее по ИТОГУ (rollout) и ВЫЖИВАНИЮ на обоих наборах (не переобучение под canon), ценой почти
  незаметного проигрыша в агрессивной зачистке/dmg_net. Диагностика подтвердила источник выигрыша:
  с ВЫКЛЮЧЕННЫМ манёвром rollout v2 обваливается к базовому (canon −3.8→−49, pool −41→−92), т.е.
  именно линия манёвра (а не сам rollout) даёт прирост выживания — ровно то, что терял прототип.
### B2–B5 — диагностика аддитивности поверх B1 (принципиально: ничего не добавляем «вслепую»)
Метод (по протоколу diagnostic-first): каждый внешний принцип — отдельным рычагом ПОВЕРХ
`battlecast_v2`, замер на canon(72)+pool(96) закрытым циклом; в код v2 попадает только доказанно
устойчивое улучшение. Итог — честные отрицательные/нейтральные вердикты, а не фиктивные фичи:
- **B2. Командный focus-fire (Wesnoth).** ⚠️ СВЕДЕНО К B1, кода НЕ добавлено. Доп. вес «добить
  угрозу / сократить число врагов» в ранжировании кандидатов дал **побитово идентичный** результат
  (canon/pool rollout совпали с дефолтом при top=6 и при top=ALL). Причина: rollout УЖЕ учитывает,
  что мёртвый враг перестаёт бить (ценность добивания встроена в исход), а `best_strike` несёт
  finisher-бонус + приоритет по `dmg_to_me`. Настоящий КОМАНДНЫЙ focus-fire ( скоординированные
  действия СОЮЗНИКОВ) вне объёма одно-акторного учителя — это полиакторный RL-уровень (Фаза D).
- **B3. Позиционная осторожность (JA2/OpenXcom).** ❌ НЕ ПРИНЯТО (сигнал переобучения). Усиление
  штрафа за входящий огонь в PRIOR кандидатов: на **честной линейке canon** CI накрывает 0
  (rollout +3.2 [−2.6, +10.9] — незначимо), выигрыш появился ТОЛЬКО на обучающем pool
  (rollout −8.9 [−18, −1.9]*). Улучшение лишь на train и ноль на fair ruler = переобучение под пул;
  по протоколу не продвигаем в дефолт v2. (Опасность позиции и так учитывает rollout; угрозу-вес
  `threat` уже можно крутить штатным параметром `BattlecastTeacher` — это гиперпараметр, не фича.)
- **B4. Dijkstra-heatmap угроз/укрытий (Brogue).** ⚠️ НЕТ АДДИТИВНОЙ ЦЕННОСТИ для battlecast.
  В нашем симе единственный сигнал опасности — зоны `reach+speed` врагов, он УЖЕ в
  `incoming_at_cell`/`reach_contacts`; УКРЫТИЙ как механики нет (см. UNSUPPORTED_MECHANICS), поэтому
  flood-fill поля не во что конвертировать. Диагностика ранжирования кандидатов (B2/B3/top-N) показала:
  порядок почти не влияет, т.к. развязку делает rollout. Поле-heatmap осмысленно лишь как ВХОД
  нейросети (голова `move`) — переносится в Фазу D как кандидат-фича наблюдения, не как тактика учителя.
- **B5. roleplayer-эвристики D&D (WIS/INT/слоты/лечение).** ❌ ЗАБЛОКИРОВАНО МЕХАНИКАМИ. В payload
  нет модификаторов INT/WIS, нет слотов заклинаний/лечения; сим не моделирует концентрацию/состояния
  (список `UNSUPPORTED_MECHANICS`). Реализовывать «приоритет цели по WIS» было бы вымыслом — не делаем.
- **DoD B:** ✅ ЗАКРЫТО честным итогом. Боевая единица усиления — B1 (`battlecast_v2`): значимо ≥
  battlecast по итогу(rollout) и выживанию на canon+pool, регресс v2/3/4/5 зелёный, базовый battlecast
  не тронут. B2–B5 исследованы и СОЗНАТЕЛЬНО не внедрены с измеренными причинами (сведено к B1 /
  переобучение / нет механики). Дальнейший рост тактики лежит в Фазе D (мульти-учитель + полиакторный
  focus-fire + heatmap как вход сети), а не в новых весах одно-акторного учителя.

### Фаза C — Новые независимые учителя-стили 🔄 (разнообразие оппонентов)
Контраст с Фазой A: там стили — battlecast с ИНЫМИ ВЕСАМИ (профиль `threat`/`ManeuverWeights`).
Здесь — поведенчески ОТЛИЧные политики: иной СПОСОБ развязки либо НОВЫЙ член функции ценности.
Правило PLAN (§Reconciled): запрещено выдавать переименованный battlecast за «стиль».
- **C1. `ufo_style`** ✅ — агрессивный планировщик «развязка ПОЛНОГО плана по исходу» (идея UFO
  `evaluate_plan`). Реализован как ПОДКЛАСС `BattlecastV2Teacher` (`@register("ufo_style")`, threat=0.7):
  отличие от базы — НЕ вес, а механизм (оценка исхода rollout над всем набором кандидатов, унаследован
  от v2), а агрессивный профиль толерантнее к входящему огню, чем v2 (threat=1.0)/ja2 (threat=1.6).
- **C3. `ja2_positioning`** ✅ — осторожный позиционный (фланг/отход) — уже готов из Фазы A (`threat=1.6`
  + высокие Disengage/Dodge). В гонке сознательно оставлен как «осторожный полюс» разнообразия.
- **C4. `cdda_ranged_support`** ✅ — скирмишер-поддержка (идея CDDA ranged keep-away). Реализован как
  ПОДКЛАСС `BattlecastTeacher` с ПЕРЕОПРЕДЕЛЁННЫМ `choose()`: к той же свёртке позиции добавлен НОВЫЙ
  член `keep_distance * (дистанция до ближайшего врага)` — отдельная цель «держать интервал», а не
  перевес `threat`. Якорь `keep_distance=0` сводит `choose()` к ПОБИТОВО базе (тест). Это reposition,
  а не fleeing: оружие и удар остаются в силе, меняется лишь выбор клетки при прочих равных.
- **C2. `wesnoth_focusfire`** ⚠️ ОТСРОЧЕН честно (кода НЕТ, по той же причине, что B2). Настоящий
  командный focus-fire — координация СРАЗУ нескольких актёров по одной цели. Наш учитель одно-акторный
  (`plan(ctx)` на одного src), а в одно-акторном frame добивание УЖЕ учтено (`best_strike` finisher +
  приоритет `dmg_to_me`, и rollout ценит «мёртвый враг не бьёт»). Отдельный одно-акторный
  «wesnoth_focusfire» был бы ровно battlecast под другим именем (запрещено). Согласованный залп —
  уровень полиакторного RL → перенесён в Фазу D (там же, куда свалились B2/B4-heatmap).
- **DoD C** ✅ (для построенных стилей): diversity-гонка `arent.teacher_bench` над всеми пятью
  (`battlecast`, `battlecast_v2`, `ja2_positioning`, `ufo_style`, `cdda_ranged_support`) на честной
  линейке stage43_canon + обучающем pool (`bench/phase_c_styles.json`). Ни один не сломан: у ВСЕХ
  `wasted_rate=0.0`, ненулевые `clear_rate`/`survival_rate`, покрытие разметки без исключений. Разнообразие
  РЕАЛЬНО и видно в метриках, а не заявлено: ufo_style держится рядом с v2 (агрессивный исход-оценщик),
  ja2 — осторожный аутсайдер по rollout, cdda — отдельный скирмишер (лучший clear_rate 0.25 и kill_rate
  0.267 на canon при сознательно отрицательном rollout: держит дистанцию вместо сближения). Это ВЕРДИКТ
  «все играют / ни один не сломан», а НЕ «кто сильнее» — сравнение силы учителей = Фаза D.

### Фаза D — Встраивание в обучение ✅ (модель стала сильнее)
Диагностика ядра показала: инфраструктура УЖЕ реестро-управляема — `dataset.generate(teacher=…)`,
`team_eval.build_controller(имя)` и `collect_asymmetric` (round-robin по `cfg.opponents`) разрешают
ЛЮБОЕ зарегистрированное имя без правок боевого ядра. Значит D — не «писать новые фичи», а (1) доказать
контракт тестами, (2) вынести честный гейт в чистую функцию, (3) подключить миксы в пайплайн/env.
- **D-контракт (enablement).** ✅ `tests/test_arent_ext_styles_training.py` (16): для каждого стиля
  (`battlecast_v2`/`ja2_positioning`/`ufo_style`/`cdda_ranged_support` + база) — он валидный v5
  BC-демо-учитель (ненулевая выборка `assert_compatible`), резолвится в `TeacherController`
  (`describe()` с префиксом имени), доигрывает командный бой как оппонент (`opponent_steps>0`), а
  `RlConfig(opponents=…, duel_opponents=…)` переносит микс через `to_dict/from_dict`.
- **D1. BC-демо мульти-учителем.** ✅ plumbing: `bc_task(..., teachers=)` — petля демо по списку
  учителей вместо жёстких `("greedy","battlecast")`.
  = прежнее поведение; mix (напр. добавить `battlecast_v2`) включается env-списком.
- **D2. Оппонент-микс в PPO.** ✅ plumbing: `ppo_task(..., opponents=)` прокидывает `RlConfig.opponents`
  (асимметричный rollout против замороженного микса) вместо `opponents=()`. Дефолт
  `S5_PPO_OPPONENTS=""` = прежний self-play; `duel_opponents` уже был env-миксом (`S5_PPO_DUEL_OPP`).
- **D3. Гейт vs микс учителей.** ✅ `arent/gate.py::gate_verdict` (чистая функция, `test_arent_gate`
  6) + `_fan` переписан на петлю по `S5_GATE_TEACHERS` (дефолт `battlecast` = прежний одиночный гейт):
  для каждого учителя agg(win/boot_lower/fights) → PASS = модель переигрывает ВСЕХ (win≥порог И
  boot-нижняя≥порог И fights≥30 на каждом), иначе `failed`/`insufficient` перечислены.
- **Fix `_fan` type casting.** ✅ Баг пофиксен: `%d` формат ломался на строковых значениях
  `n_hero`/`n_foe`/`fights`, пришедших из Ray remote-task транзитом. Явное `int(...)` перед
  `%d` добавлено в `_fan` (строки ~300-302 в `ray_stage5_pipeline.py`). Регресс тестов зелёный.
- **`launch_s5.ps1` дополнен env-иксами микса.** ✅ Строки 10–12 (закомментированы, ASCII): рекомендуемый
  mix учителей для кластерного прогона Phase D. Дефолт остаётся прежним (`battlecast` only для гейта,
  `greedy,battlecast` для BC-демо, self-play для PPO), поэтому текущий прогон не изменится молча.
- **D4. Куррикулум силы.** ✅ РЕАЛИЗОВАН В ЯДРЕ (раньше был «операционный, без кода»): в
  `arent/rollout.py` добавлено `RlConfig.curriculum` = стадии `(start_iter, набор_оппонентов)`,
  чистые `parse_curriculum(spec)` / `curriculum_opponents(cfg, it)`; `rl.run` на каждой итерации
  берёт активный набор и передаёт его в `collect(..., opponents=…)` → `collect_asymmetric`. Пустое
  расписание = прежнее равномерное поведение (обратная совместимость, покрыто тестами). Env-формат
  пайплайна: `S5_PPO_CURRICULUM='0:battlecast;20:battlecast,ufo_style;30:battlecast,ufo_style,cdda_ranged_support'`
  (парсится на драйвере, передаётся в `ppo_task`). Тесты: `tests/test_arent_curriculum.py` (9✅:
  порядок стадий, границы итераций, фолбэк до первой стадии, purity, JSON-round-trip). Осталось
  **эмпирически** прогнать staged-цепочку на кластере и сравнить с равномерным миксом (числовой замер).
- **Запуск (эмпирика, делает пользователь на кластере):**
  `$env:S5_BC_TEACHERS='greedy,battlecast,battlecast_v2'; $env:S5_PPO_OPPONENTS='battlecast,ufo_style,cdda_ranged_support'; $env:S5_GATE_TEACHERS='battlecast,battlecast_v2,ufo_style,ja2_positioning,cdda_ranged_support'; python .ray/ray_stage5_pipeline.py`
  (см. `launch_s5.ps1`; в финале печатается `RESULT_JSON` с `bc_gate.verdict`/`ppo_gate.verdict`).
  После обрыва связи на PPO-фазе: добавить `$env:S5_SKIP_BC='1'` — пайплайн пропустит BC и стартует
  PPO с сохранённого `arent/runs/s5bc/model.json` (проверяется `schema=5`), не теряя дорогую BC-фазу.
- **DoD D (✅ выполнен на GPU-кластере, 10.11.2026):** числовой вердикт гейт-микса получен реальным
  прогоном (BC resume с `s5bc` → PPO 40 iters `warm=s5bc` → гейт vs 5 учителей). Пороги прежние
  (win≥0.50, boot_lower≥0.50, fights≥30 на каждом), **не двигались**. Лог: `.ray/stage5_cluster_resume.log`.
  - **BC без PPO (s5bc): FAIL** — worst_win=**0.4907**, `failed=['cdda_ranged_support']`
    (win 0.4907 / boot 0.4630). Остальные 4 пройдены (0.675–0.777).
  - **BC+PPO (s5ppo): PASS** — worst_win=**0.6204**, `failed=[]`, `insufficient=[]`, по 864 бою на учителя:

    | учитель | win_rate | boot_lower | вердикт |
    |---|--:|--:|:-:|
    | battlecast | 0.7604 | 0.7361 | PASS |
    | battlecast_v2 | 0.7616 | 0.7373 | PASS |
    | ufo_style | 0.7454 | 0.7199 | PASS |
    | ja2_positioning | 0.8356 | 0.8148 | PASS |
    | cdda_ranged_support | 0.6204 | 0.5926 | PASS |

  - **Вывод:** PPO-микс (D2) поднял именно слабое место BC — `cdda_ranged_support` 0.4907 → **0.6204**
    (+0.13): асимметричный rollout против замороженных стилей реально закрывает разрыв. Duel-отбор best
    vs `battlecast`: 0.7083 (final 0.6992, 1210 боёв), 40 iters, 14416 сцен, PPO 27903 с; весь прогон
    ~9.1 ч. `_fan` int-fix подтверждён — гейт-строки напечатались без падений.

---

## 3. Лицензионные и технические guardrails (обязательно)

- **Копировать код можно** только у MIT/permissive и с сохранением copyright-notice: OpenCombatEngine
  (MIT код + OGL на SRD-данные — не тянуть WotC trade dress/логотипы), mookAI (MIT).
- **Только идеи/независимая реализация** (не копировать код, имена структур, формулировки, числовые
  константы дословно) для: UFO, Wesnoth (GPL-2.0+), OpenXcom (GPL-3.0), MegaMek (GPLv3 + CC BY-NC-SA
  данные — в коммерч. НЕ тянуть данные), Cataclysm DDA (CC BY-SA 3.0), JA2 v1.13 (лицензия не подтверждена),
  Battle Brothers / Smart Combat NPC / Tactical Troops (закрыто).
- **JA2 оригинал (SFI-SCLA) и dnd-rl (LICENSE нет)** — кодовый перенос запрещён, пока статус не ясен.
- Фильтр: берём формулу-идею → своя функция под НАШИ правила → сверяем с симулятором, а не с оригинальной игрой.

---

## 4. Шаблон «изучения одного источника» (заполнять в `search_teacher/sources/<slug>.md`)

Для каждого варианта из §1 зафиксировать:
1. **Что читали** (точные файлы/функции): UFO `g_ai.cpp::AI_FighterCalcActionScore`; Wesnoth
   `default/attack.cpp` + `ai.get_attacks()` + AiWML attack eval; JA2 `DecideAction.cpp` + docs; MegaMek
   `FireControl`/`EnemyTracker`/`BehaviorSettings`; Cataclysm reposition/assess_danger; Brogue Dijkstra
   maps; OpenXcom AIMode/Xilmi cover; OpenCombatEngine ADR 0002; roleplayer `data_battle.py`;
   DnD5e-CombatSimulator `world.py`/`behavior.py`.
2. **Извлечённая эвристика** одной формулой/псевдокодом (наши heads).
3. **На какую голову v5 ложится** и какой счётчик метрики нужен.
4. **Лицензионный вердикт** (код нельзя/можно; данные).
5. **Как проверить силу** (какой матч A2, ожидаемый сдвиг метрик).
6. **Решение**: в battlecast-2.0 (B) / отдельный стиль (C) / справочник (отложить).

---

## 5. Порядок работ

0. **Фаза 0** ✅ (верификация источников) — готова, см. `PHASE0.md`; приоритеты подтверждены/поправлены.
1. **Фаза A** (бенчмарк) ✅ — A1+A2+A3 готовы; гонка `python -m arent.teacher_bench` пишет
   `bench/baseline_vs_ja2.json`. Следующий шаг — Фаза B (усилить battlecast).
2. **Фаза B** (усилить battlecast) ✅ — наибольший рычаг, нулевой лицензионный риск. B1 закрыт:
   `battlecast_v2` (развязка по исходу сима над полным набором кандидатов + манёвр), артефакт
   `bench/battlecast_v2_vs_base.json`, регресс базы зелёный. B2–B5 продиагностированы и сознательно
   НЕ внедрены (B2 сведено к B1; B3 — переобучение под pool; B4/B5 — нет механики в симе). Следующий
   шаг — Фаза C (стили) и/или Фаза D (подключение v2 как второго учителя в BC/гейт + полиакторный
   focus-fire + heatmap как вход сети).
3. **Фаза C** (стили) ✅ — добавлены поведенчески-отличные `ufo_style` (подкласс v2, агрессивный
   исход-оценщик) и `cdda_ranged_support` (новый член ценности `keep_distance`, якорь 0 = база);
   `ja2_positioning` живёт с Фазы A. Diversity-гонка всех пяти (`bench/phase_c_styles.json`): все
   играют, `wasted_rate=0`, ни один не сломан. `wesnoth_focusfire` честно отсрочен в D (одно-акторный
   эквивалент = battlecast под именем; настоящий focus-fire — полиакторный RL). Следующий шаг — Фаза D
   (подключение v2/ufo/cdda как оппонент-микса в BC/гейт + полиакторный focus-fire + heatmap-вход сети).
4. **Фаза D** (мульти-учитель в BC + оппонент-микс в PPO/гейте) ✅ — замер роста выполнен,
   DoD D PASS (worst_win 0.6204). **D4 (куррикулум weak→strong): код ядра готов** (`RlConfig.curriculum`,
   `test_arent_curriculum` 9✅, env `S5_PPO_CURRICULUM`) — остался кластерный staged-замер против
   равномерного микса. **Остаётся отдельно:** полиакторный `wesnoth_focusfire` (кода нет — multi-agent RL).
5. Параллельно: заполнять `sources/<slug>.md` по шаблону §4 для всех вариантов из §1.

**Опорные точки в коде:** `arent/teachers.py` (@register/get_teacher/_autoload), `arent/team_eval.py`
(build_controller/fight_teams), `arent/abset.py` (A/B), `arent/battlecast.py` + `arent/battlecast_heuristics.py`
(усиление B), `points.json` `tactics` (веса/пороги), `arent/dataset.py` (`generate(teacher=...)`),
`arent/rollout.py` (`RlConfig.duel_opponents`), `.ray/ray_stage5_pipeline.py` (`_fan`/гейт),
`spec5` (манёвры), `scenarios.generate_stage43_pool/_canon` (сцены).
