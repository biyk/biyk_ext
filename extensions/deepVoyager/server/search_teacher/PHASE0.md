# Фаза 0 — верификация источников (пригодность учителей)

> Ход работ: web-заход в первичные источники (репозитории/доки/лицензии) по каждому кандидату
> из `deep.md`/`cgpt.md`, чтобы снять пометки «проверить LICENSE / не подтверждено» и решить,
> что реально портируем в УЧИТЕЛЕЙ. Дата проверки: 2026-11-05. Все ссылки — первичные.

## 0.1 Итоговая таблица вердиктов (после Ф0)

Легенда «Лицензия»: ✅=подтверждено в первичном источнике этим проходом; 📄=по описаниям
агентов (вердикт «только идеи» от точной лицензии не зависит).

| Кандидат | Лицензия (проверка) | Что реально найдено | Пригодность под наши головы | Вердикт Ф0 → приоритет |
|---|---|---|---|---|
| **roleplayer** (PyPI 3.0.1, siwpan) | **MIT ✅** (код) + CC-BY-4.0 (SRD-данные) | Полный пошаговый бой: инициатива/раунды/экономия действий (attack/**Dash**/cast/recharge/saves), состояния, death-saves, легендарные; **Monster AI** (nearest / WIS≥12 wounded-priority / INT≥18 expected-damage-optimal), **PC AI** (focus-fire min-HP, yo-yo healing), политики cautious/aggressive, seed-детерминизм, `data_battle.py` | `target`,`weapon`,`maneuver(dash/heal)` — ДА; `move`(сетка/cover/OA) — НЕТ (бой абстрактный) | **Главный permissive D&D-источник → B5 + BC-демо-учитель. P1 ✅** |
| **OpenCombatEngine** (jamesplotts) | **MIT ✅** (код) + OGL/SRD 5.1 | C#/.NET8. ADR: grid(0028), flanking(0035), OA(0036), AStar(0039), concentration(0041), LoS(0032), AoE(0033), move-cost(0034). **Но ИИ базовый** (ADR 0002: finisher по low-HP%+proximity, flee<30%; ADR 0003: только Artillery kiting 30–60ft, Tank/Brute=future) | `move`(позиция/дистанция) идеи; не ранний учитель | **Даунгрейд подтверждён → справочник архитектуры/правил, НЕ учитель. P-справочник ✅** |
| **UFO: Alien Invasion** (ufoaiorg) | **GPL-2.0 ✅** | `g_ai.cpp` планировщик: перебор достижимых позиций × варианты стрельбы × TU-стоимость × ожидаемый урон × kill-шанс × опасность позиции × уход в укрытие после | все 4 головы (принцип `evaluate_plan`) | **Учитель-принцип №1 (только идеи). P1 ✅** |
| **Battle for Wesnoth** (wesnoth) | GPL-2.0+ 📄 | RCA AI: candidate actions, оценка комбинаций атакующих по цели, chance-to-kill, avg/candidate losses, terrain quality, aggression, retreat/heal | `target`(team focus-fire), `weapon`, `move` | **Учитель focus-fire (только идеи). P1** |
| **Jagged Alliance 2 / Stracciatella** | **SFI-SCLA (не OSI) ✅** (LicenseRef-SFI-Source-Code, AUR) | Док-я: фланг/cover/подавление/дым/отход/friendly-fire; код открыт для чтения, НЕ для копирования | `move`/`maneuver`(осторожный позиционный) | **Учитель позиционирования (только идеи/док). P2** |
| **OpenXcom** (OpenXcom) | **GPL-3.0 ✅** | Клон X-COM; фазовый скоринг/cover (мод-ИИ Xilmi) | `move`/`maneuver`(cover-anchors) | **Референс cover-скоинга (только идеи). P2** |
| **Brogue / Brogue CE** | **AGPL-3.0 ✅** (CE-fork) | Dijkstra heatmaps (flood-fill) — дешёвая детерминированная функция поля | `move`(kiting/retreat/cover) | **Алгоритм heatmaps → реализовать НЕЗАВИСИМО (код не тащим, AGPL). P2** |
| **Cataclysm: DDA** | CC BY-SA 3.0 📄 | Различение `repositioning` vs `fleeing`, preferred-range, поддержка стрелков | `move`/`maneuver`(дистанц. стиль) | **Стиль ranged_support (только идеи). P3** |
| **MegaMek (Princess)** | GPLv3 + CC BY-NC-SA данные 📄 | EnemyTracker/FireControl/BehaviorSettings | `move`/`target`/`weapon`(угроза) | **Отложить (данные NC!). P3** |
| **Battle Brothers** | закрыто 📄 | utility-профили архетипов, AP-aware | стили | **Только описания. P3** |
| **Smart Combat NPC** | коммерч. закрыто 📄 | каталог D&D-поведений | — | **Каталог идей. справочник** |
| **DnD5e-CombatSimulator** (asahala) | не подтверждена 📄 | Python 2D grid/pathfinding/formation, behavior.py (Standard/SocialAnimal) | `move` каркас | **Опц. pathfind-референс (Python). P3** |
| **dnd-ml / dnd-rl** | LICENSE не найден 📄 | OA-aware pathfinding/концентрация/слоты; продвинутый ИИ=future | ориентир механик | **Справочник. не копировать** |

**Отброшено окончательно** (как и агенты): LLM-боты (недетерминированы), закрытые RTS/шахматно-го движки.

Первичные ссылки:
- roleplayer — https://pypi.org/project/roleplayer/ , репозиторий https://gitee.com/siwpan/roleplayer
- OpenCombatEngine — https://github.com/jamesplotts/opencombatengine (+ docs/adr/0002, 0003)
- UFO — https://github.com/ufoaiorg/ufoai , doxygen `g__ai_8cpp`
- Wesnoth — https://github.com/wesnoth/wesnoth , https://wiki.wesnoth.org/AI_Framework
- JA2 Stracciatella — https://github.com/ja2-stracciatella/ja2-stracciatella , https://1dot13.github.io/documentation/
- OpenXcom — https://github.com/OpenXcom/OpenXcom
- Brogue CE — https://github.com/tmewett/BrogueCE

## 0.2 Ключевые поправки к плану после Ф0
1. **roleplayer = самый рычащий легальный источник.** Единственный подтверждённый **MIT + D&D-специфичный + готовый inspectable AI**. Он закрывает `target`/`weapon`/`maneuver(dash,heal)` без лицензионного риска → идёт и в **B5 (эвристики)**, и как **BC-демо-учитель** (готовая сильная D&D-политика).
   Ограничение Ф0: бой абстрактный (нет клетки/cover/OA) → для `move`/cover-гейд-манёвров Disengage/Dodge опираемся на UFO/Wesnoth/JA2-принципы, а не на roleplayer.
2. **OpenCombatEngine понижён подтверждённо** (ADR 0002/0003 = базовый ИИ). Не учитель. Но его ADR-картотека (AStar/flank/OA/concentration/AoE/LoS) — полезный **референс при сверке нашей легализации и метрик манёвров**.
3. **Brogue уточнён: AGPL-3.0**, а не «probably permissive». Алгоритм Dijkstra-map реализуем независимо (математика не охраняется) — код форка не тянем.
4. **Конфликт агентов по №1 разрешён данными**: связка UFO(планирование)+Wesnoth(фокус-огонь)+JA2(позиция) как принципы + roleplayer как готовая D&D-политика. Это и есть ядро Фаз B/C.

## 0.3 Что не перепроверяли (и почему это не важно для Ф0)
Точные версии GPL/CC у Wesnoth/Cataclysm/MegaMek/OpenXcom-мода и лицензию DnD5e-CombatSimulator
не сверяли построчно — потому что их вердикт **«только идеи / независимая реализация»** от этого не
меняется (permissive они или copyleft — код всё равно не копируем в наш несовместимый проект).
Перепроверить обязательно ПЕРЕД любым копированием кода, если что-то из них станет permissive-годным.

## 0.4 Вывод Фазы 0 → стартуем Фазу A
Данные собраны, пригодность оценена, приоритеты подтверждены. Переходим к **Фазе A**
(инфраструктура измерений): реестр внешних политик-заглушек + расширенные метрики `abset.py`,
чтобы усиление battlecast (B) и новые стили (C) мерить честно, а не «на глаз».
