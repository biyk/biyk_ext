Ниже — результат двухпроходного анализа: сначала я собрал факты по открытым репозиториям, спецификациям и статьям, затем отранжировал кандидатов именно под вашу схему `move / target / weapon / maneuver` и требование детерминированных эвристик.

Сразу важное ограничение: **кандидатов, которые одновременно (а) заточены под D&D 5e, (б) имеют открытый код с permissive-лицензией и (в) уже demostrably сильны в тактике**, немного. Придётся комбинировать «домен D&D» с «переносимыми тактическими эвристиками из соседних TBT-движков».

---

## 1. Сводная таблица кандидатов

| Кандидат | Тип / домен | Сильные стороны | Слабости / риск | Лицензия | Портируемость (1–5) | Покрытие манёвров (1–5) | Оценка как учителя (1–5) |
|---|---|---|---|---|---|---|---|
| **OpenCombatEngine** | D&D 5e SRD combat engine, C# | Заявлены Tier 2 (Tactical targeting / self-preservation) и Tier 3 (Role-based: Artillery = kiting, Brute); action system, spell slots, cyclic initiative — всё в одном месте | Tier 2/3 могут быть зачаточными; нет публичных замеров силы; C#-кодовая база, не Python | **MIT** (код) + OGL 1.0a (механики) | 4 | 3 | **4** |
| **DnD5e-CombatSimulator** | D&D 5e creature combat simulator, Python | Чистый Python без зависимостей для ядра; явный `behavior.py` с AI behaviors (Standard, SocialAnimal); `world.py` с 2D grid / pathfinding / formation | Behavior пока простой (Standard/SocialAnimal), не заявлен как «сильный тактик»; нет cover/focus-fire как first-class | Не указана явно в сниппете (нужна проверка repo) | **5** (Python, читаемые модули) | 2–3 | 3 |
| **roleplayer** (PyPI) | D&D 5e battle simulator с AI-эвристиками | Прямо описаны эвристики: **PC AI — фокус на enemy с минимальным HP**, monster AI — nearest / wounded priority / expected-damage optimal в зависимости от WIS/INT; полная симуляция action economy, spell slots, legendary actions | Это пакет-симулятор, не «движок для порта»; эвристики простые, но **готовые к переписыванию** в чистые функции | PyPI-пакет (нужна проверка лицензии; вероятно permissive) | 5 (Python, явные правила) | 3 (есть spell/slot, но манёвры Dash/Disengage/Dodge не акцентированы) | **4** (как источник готовых D&D-эвристик) |
| **mookAI** | FoundryVTT D&D 5e AI для «mook» NPC | Детерминированный цикл: найти цель по vision → выбрать → проложить бесколлизионный путь → подойти → атаковать → end turn | Scope сознательно ограничен: **low-intelligence mooks**, без focus-fire, kiting, cover-seeking; не «сильный учитель» | **MIT** (обновлённая версия оригинального MookAI) | 4 (JS/Foundry, но логика простая) | 1–2 | 2 |
| **Wesnoth AI (default/attack.cpp)** | Пошаговая фэнтези-тактика (hex/grid), C++ | Зрелый код: **aggression**, chance-to-kill, alternative terrain quality, CTD-aware attack selection, leader value, caution; покрывает «атаковать или отступить» через aggression/CTD | Не D&D: нет spell slots, concentration, opportunity attacks в 5e-смысле; GPL-код нельзя копировать в закрытый permissive-проект без последствий | **GPL v2+** (код) | 2 (идеи — да, код — ограниченно) | **4** (позиционирование, aggression, риск) | **4** (по тактической зрелости) |
| **OpenXcom AI (AIModule / Xilmi AI)** | XCOM-подобная пошаговая тактика, C++ | Явная **phase-based scoring**: attack-move → scouting-move → cover-seeking с учётом spotted/unspotted; aggression влияет на cover-seeking; прозрачные AIMode (PATROL/AMBUSH/COMBAT/ESCAPE) | Realtime-происхождение (TU-система), нет D&D action economy; GPL | **GPL-3.0** (+ CC-BY-SA assets) | 3 (эвристики хорошо документированы, код GPL) | **5** (cover, scouting, escape, ambush) | **4** |
| **Jagged Alliance 2 v1.13 / Stracciatella** | Пошаговая тактика с grid, C | Готовые action-константы: **AI_ACTION_FLANK_LEFT / RIGHT, TAKE_COVER, SEEK_OPPONENT**; DecideAction.cpp с логикой flank distance и cover; зрелая боевая логика | Очень старая кодовая база; лицензия **SFI-SCLA** — не OSI, «educational purposes only» в некоторых репозиториях; юридически рискованно | **SFI Source Code License Agreement** (не permissive) | 2 (идеи — да, код — нет) | **5** (flank, cover, seek, retreat) | 3 (сильный, но лицензионный риск) |
| **TurnBasedEngine (samsmithnz)** | XCOM/Jagged Alliance-подобный turn-based engine, C# | Есть **high/low cover, cover destruction**, базовый AI, который пытается **move, flank, attack** | AI заявлен как “very basic”; нет продвинутого focus-fire / target priority | GitHub repo (лицензия требует проверки; вероятно MIT) | 4 | 3 | 2–3 |
| **Brogue (Dijkstra Maps)** | Roguelike tactical AI | Подход **Dijkstra Maps / heatmap**: flood-fill от player position, каждый tile получает возрастающее число; даёт естественное **kiting, retreat, pathing toward/away** | Не D&D; нет action economy, spell slots, opportunity attacks | Открытый код (проверить лицензию; обычно permissive для roguelike) | **5** (алгоритм легко переносится) | **4** (позиционирование, retreat, kiting) | **4** (как «дикий» кандидат) |
| **Warbringers.py** | Пошаговый wargame simulator с MCTS / evolutionary AI, Python | Явно про **multi-action, stochastic, adversarial** сценарии; units двигаются, сражаются, стреляют; terrain modifiers и positional advantages; framework для сравнения AI-стратегий | Не D&D; MCTS-компонент может быть «чёрным ящиком», но **эвристики для rollout можно инспектировать** | GitHub (лицензия требует проверки; академический проект) | 4 (Python) | **4** (move/fight/shoot/positioning) | 3 |
| **Tactical Troops: Anthracite Shift** | Squad-based tactics, Utility AI + MCTS | Иерархическая комбинация **Utility AI (стратегический слой) + MCTS (тактический слой)**; Utility AI даёт явные scoring-функции для высокоуровневых решений | Нет открытого кода (описана архитектура в paper); MCTS недетерминирован, но **utility-часть можно портировать как эвристики** | Только paper / проприетарная игра | 3 (по статье/псевдокоду) | **4** (позиционирование, target selection через utility) | 3 (ценен как дизайн-референс) |

**Отброшены как явно неприменимые:** LLM-based `foundry-vtt-dnd-combat-ai` (недетерминирован, «чёрный ящик»); `Familiar` (проприетарный сервис); `For The King` (закрытый, эвристики не документированы); Freeciv / 0 A.D. (RTS-макро, не TBT-микро); чисто шахматные/го-движки.

---

## 2. ТОП-3 рекомендации с планом портирования

### 🥇 #1: OpenCombatEngine + roleplayer как «D&D-эвристический слой»

**Почему первым:** это единственный кандидат, который одновременно находится **внутри домена D&D 5e SRD**, имеет **MIT-лицензию** на код и уже заявляет уровни AI, включая **role-based artillery (kiting)** и **self-preservation**. `roleplayer` дополняет его **готовыми, явно описанными эвристиками** для target priority и spell usage.

**План портирования (в ваши 4 головы):**

| Ваша голова | Что взять | Откуда |
|---|---|---|
| **Move** | Self-preservation logic: если HP ниже порога → отступить к cover / увеличить дистанцию; иначе двигаться к позиции, откуда доступна лучшая цель (pathfinding из `world.py`) | OpenCombatEngine Tier 2 + DnD5e-CombatSimulator `world.py` |
| **Target** | **Focus-fire enemy с минимальным текущим HP** (PC AI из `roleplayer`); monster AI — nearest / wounded priority в зависимости от WIS, expected-damage optimal при INT≥18 | roleplayer `data_battle.py` |
| **Weapon** | Expected-damage optimal: перебор доступных оружий/заклинаний и выбор с максимальным `P(hit) × expected_damage`; учитывать spell slots (не тратить высокий слот на low-HP цель, если можно добить cantrip) | OpenCombatEngine spell resolution + roleplayer expected-damage |
| **Maneuver** | Kiting для «Artillery»-роли: если цель в melee reach, **Disengage** → отойти на дистанцию; если цель далеко и нужно сблизиться — **Dash**; если ожидаемый входящий урон высок и позиция плохая — **Dodge** (пока как простая эвристика, т.к. в OpenCombatEngine явного Dodge не заявлено) | OpenCombatEngine Tier 3 + собственная обёртка |

**Потолок силы vs battlecast:** OpenCombatEngine **не обязательно сильнее** battlecast «из коробки» (нет публичных бенчмарков). Его ценность — в **чистой, MIT-лицензированной архитектуре D&D-правил**, на которую можно навесить более сильные эвристики без юридических рисков. battlecast, судя по описанию, уже имеет «complete combat AI with four team tactics» — значит, OpenCombatEngine нужно **усиливать** эвристиками из roleplayer и Wesnoth/OpenXcom, а не просто включать.

---

### 🥈 #2: Wesnoth AI (`default/attack.cpp`) — как источник зрелых тактических эвристик

**Почему вторым:** несмотря на GPL и не-D&D домен, Wesnoth даёт **самый проверенный временем и хорошо документированный набор эвристик** для «атаковать или нет» с учётом риска, terrain quality, aggression и leader value. Его логика **естественно ложится на вашу голову `weapon` + `target` + частично `move`**.

**Конкретные эвристики для портирования:**

1. **Aggression-параметр** (0.0–1.0): при `aggression < 1` AI не атакует, если `CTD (chance to die) > aggression`. Это готовый механизм для **Dodge/Disengage**: если `P(получить lethal damage) > threshold`, выбирать оборонительный манёвр вместо атаки.
2. **Alternative terrain quality**: при выборе позиции оценивать не только «где стою», но и **лучшую достижимую defensive terrain** после движения. Это прямо ложится в `move`: не идти в открытое поле, если в пределах reach есть укрытие.
3. **Leader value / caution**: если у цели высокий «лидерский» вес, AI может игнорировать риск и фокусить её. Аналог **target priority** для «командиров» / spellcasters в вашем симуляторе.
4. **Poisoned units only attacked if chance to kill**: эвристика «не тратить атаку на цель, которую всё равно не добить, если есть более важная цель» — прямой кандидат в `target`.

**Потолок силы:** Wesnoth AI **слабее battlecast в D&D-специфике** (нет spell slots, concentration, opportunity attacks в 5e-форме), но **сильнее в риск-менеджменте позиционирования** — он явно оценивает «умру ли я, если пойду туда». battlecast, вероятно, лучше в «заклинательной» части, но Wesnoth может дать более консервативное / риск-осознанное поведение.

**Лицензионный нюанс:** GPL v2+. **Нельзя копировать код** в permissive-проект, но **можно переписать эвристики на свою реализацию** (идеи и формулы не охраняются копирайтом так же, как код; но прямые числовые константы и структуру лучше не копировать дословно).

---

### 🥉 #3: OpenXcom AI (Xilmi / AIModule) — как источник phase-based scoring и cover/scouting

**Почему третьим:** OpenXcom даёт **готовую декомпозицию хода на фазы** и **явные оценки для cover-seeking / scouting / escape**, что напрямую закрывает вашу слабую голову `maneuver` (Dash/Disengage/Dodge). GPL-3.0 — та же юридическая оговорка, что и с Wesnoth: **идеи и псевдокод — да, дословный код — нет**.

**Что взять:**

- **Phase-based scoring**: сначала оценить **best attacking-move**, затем **best scouting-move**, затем **best cover-move**. В вашей архитектуре это означает: не выбирать maneuver независимо, а **сначала проверить, есть ли выгодная атака**, и только если нет — уходить в scouting/cover.
- **Spotted / unspotted логика**: если AI не думает, что его заметили, он сначала **peek**, затем движется к **лучшему cover, которое ближе к предполагаемой позиции врага**. Это готовый рецепт для `move` + `maneuver`: **Disengage** не всегда «отступить назад», а «перейти в cover, сохраняя давление».
- **Aggression 1–2 меняет cover-seeking**: можно параметризовать «стиль» оппонента (агрессивный vs оборонительный) без переписывания всей логики.

**Потолок силы vs battlecast:** OpenXcom AI **сильнее в «неопределённости»** (fog of war, spotted/unspotted, escape/ambush), но **слабее в D&D-ресурсах**. В вашем симуляторе с полной информацией (если нет fog) часть логики потеряет смысл, но **phase-based подход и cover-seeking** остаются полезными.

---

## 3. «Дикий» кандидат: Brogue (Dijkstra Maps) — для расширения стилей через kiting/retreat

**Почему «дикий»:** это не D&D и не движок боя в вашем смысле, но **алгоритм Dijkstra Maps** даёт исключительно **дешёвый и детерминированный способ реализовать kiting, retreat и позиционирование**, которые в D&D-движках часто не являются first-class.

**Как работает:** вы строите heatmap от позиции врага (0 в точке врага, +1 за каждый шаг flood-fill). Тогда:
- **Move toward** = идти в клетку с меньшим числом;
- **Kiting / retreat** = идти в клетку с **большим** числом, но так, чтобы не попадать в opportunity attack;
- **Cover-seeking** = комбинировать heatmap врага с heatmap «опасных линий огня» (LOS).

**Почему это сильно:** в отличие от «жадного» выбора цели, Dijkstra Maps позволяют AI **одновременно** учитывать дистанцию до врага и до укрытия, не перебирая все комбинации. Это **чистая функция** от состояния поля — идеально для вашего требования детерминизма.

**В вашу схему:**
- `move`: шаг в направлении, которое **увеличивает** «вражеский» heatmap-скор (kiting) или **уменьшает** его (engagement), в зависимости от роли.
- `maneuver`: если текущая клетка имеет высокий «риск opportunity attack» → **Disengage** (шаг, который не провоцирует OA) или **Dash** (если нужно быстро разорвать дистанцию).

**Ограничение:** Brogue — roguelike, там нет action economy. Вам придётся **наложить** свою action economy сверху: например, считать, что Disengage стоит «манёвр-слота», а Dijkstra-шаг — «движения». Но это как раз хорошо ложится на вашу 4-головую схему.

---

## 4. Красные флаги по лицензиям и зависимостям

| Кандидат | Лицензия | Красный флаг | Что можно / нельзя |
|---|---|---|---|
| **OpenCombatEngine** | **MIT** (код) + **OGL 1.0a** (механики) | OGL требует сохранять copyright notice и не использовать закрытые trade dress / логотипы WotC. Код — полностью permissive. | ✅ Можно копировать код и эвристики в закрытый/открытый проект при сохранении notice. ⚠️ Механики — соблюдать OGL. |
| **roleplayer** | Не подтверждена в сниппете | PyPI-пакет может быть **GPL / AGPL** или **proprietary**. Нужно проверить `LICENSE` в пакете перед копированием кода. | ⚠️ Если GPL — только идеи/переписывание; если MIT/BSD — можно код. |
| **mookAI** | **MIT** | Scope ограничен mook-ами; логика слишком простая для «сильного учителя». | ✅ Можно брать pathfinding / vision-цикл; ❌ не даст силы. |
| **Wesnoth AI** | **GPL v2+** | **Copyleft**: если вы включаете GPL-код в свой проект, ваш проект тоже должен быть GPL-совместимым. Для закрытого симулятора — **нельзя копировать код**. | ⚠️ **Только переписывание эвристик** на свою реализацию. Идеи (aggression, CTD-threshold, terrain quality) не запрещены. |
| **OpenXcom AI** | **GPL-3.0** (+ CC-BY-SA assets) | То же, что Wesnoth: **сильный copyleft**. CC-BY-SA на assets может «заразить» и производные. | ⚠️ Только псевдокод / концепции; код — нет. |
| **Jagged Alliance 2** | **SFI-SCLA** (не OSI) | **Не open source** в OSI-смысле; «educational purposes only» в ряде репозиториев. Коммерческое использование и даже включение в продукт — юридически рискованно. | ❌ **Не рекомендую** для портирования кода. Только идеи (flank/cover action names). |
| **TurnBasedEngine** | Не подтверждена | Может быть MIT, но нужно проверить. AI заявлен как basic. | ⚠️ Проверить LICENSE; вероятно, можно брать структуру. |
| **Brogue** | Открытый код (проверить) | Roguelike-лицензии обычно permissive (Apache/MIT/BSD), но **нужно проверить** конкретный repo. | ✅ Алгоритм Dijkstra Maps можно реализовать независимо; код — после проверки. |
| **Warbringers.py** | GitHub, не подтверждена | Академический проект; лицензия может быть MIT/Apache, но нужно проверить. | ⚠️ Проверить LICENSE перед копированием. |
| **Tactical Troops** | Только paper | **Нет открытого кода**. Можно брать **идеи utility-функций** из статьи, но не код. | ✅ Идеи/псевдокод. ❌ Код. |

**Отдельный красный флаг:** `foundry-vtt-dnd-combat-ai` (LLM-based) — **недетерминирован** и не подходит под критерий «чистые функции». Даже если лицензия permissive, поведение зависит от модели и prompt-а, а не от состояния поля.

---

## 5. Итог одной строкой

**Взять в первую очередь = OpenCombatEngine (MIT) в связке с эвристиками roleplayer, потому что это единственный кандидат в домене D&D 5e с permissive-лицензией и готовой архитектурой action economy, на которую можно чисто навесить focus-fire, expected-damage и self-preservation без юридических рисков.**