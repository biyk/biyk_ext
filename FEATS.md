# FEATS.md — каталог приёмов создания и обслуживания способностей в `biyk_ext`

Документ описывает **все реально используемые в этом модуле способы** сделать заклинание,
способность, черту (feat), реакцию, пассивный трекер или внешнюю интеграцию. Цель — переиспользовать
наработку, а не изобретать заново.

Источник: `main.mjs`, `settings.mjs`, `registry.js`, `extensions/*/index.js`,
`extensions/deepVoyager/{actions,utils}/*`, `extensions/weather_by_day_time/*`.

---

## 0. ОГЛАВЛЕНИЕ + быстрый индекс (читать отсюда)

**TL;DR:** расширение = `extensions/<имя>/index.js` с `export function init()` + одна строка в
`registry.js`; билды нет, чекбокс в настройках появляется сам. Всего 15 разделов, ~1143 строки.
Номера строк ниже — для текущей версии файла; если после правок съехали, обнови одной командой:
`Select-String -Path FEATS.md -Pattern '^#{2,3} ' | Select-Object LineNumber, Line`

### 0.1 «Хочу сделать …» → куда смотреть

| Хочу … | § | Строки | Эталон в коде |
|---|---|---|---|
| проверить, нет ли уже такого расширения | §1 | 73–109 | `registry.js` — все 35 ключей с метками |
| подключить/зарегистрировать расширение | §1 | 73–109 | `registry.js`, `main.mjs` |
| выбрать хук под задачу (20+ точек входа) | §2 | 110–140 | таблица §2 |
| способность «использовал предмет → сделать Y» | §3.1 | 143–169 | `ArcaneRecovery` |
| бафф/дебафф ActiveEffect из кода (advantage, temp HP) | §3.2 | 170–222 | `EnhanceAbility` |
| повесить/снять статус (Blinded, Poisoned, Invisible) | §3.3 | 223–261 | `blindness_deafness`, `activate_effect` |
| реакция: можно ли реагировать + трата | §3.4 | 262–287 | `warlord_help`, `guardian-shield` |
| менять advantage / урон / цели в workflow | §3.5 | 288–322 | `avoid`, `sharp_shooter` |
| спасбросок цели, DC, противоположный бросок | §3.6 | 323–344 | `possessed-items`, `enemy_spoted` |
| ячейки заклинаний, очки вместо ячеек | §3.7 | 345–373 | `DivineRecovery`, `stas_char` |
| список доступных действий существа | §3.8 | 374–405 | `deepVoyager/utils/help.js` |
| диалог выбора/подтверждения, live-валидация, таймаут | §4.1–4.4 | 408–475 | `ArcaneRecovery`, `attack-of-opportunity` |
| своя кнопка в UI, заметки ГМа, резать лист игроку | §4.5–4.6 | 476–497 | `messageBox.js`, `renderActorSheet` |
| поймать перемещение токена | §5.1 | 500–513 | `attack-of-opportunity` |
| расстояние в футах/клетках (4 способа, Chebyshev) | §5.2–5.3 | 514–538 | `combatDistance`, `PackTacticsCheck` |
| коллизии/проходимость с фолбэком по версиям | §5.4 | 539–550 | `deepVoyager/actions/move.js` |
| видимость и Line of Sight | §5.5 | 551–569 | `enemy_spoted`, `guardian-shield` |
| «роза движения» — свободные клетки в 8 направлениях | §5.6 | 570–574 | `utils/tokenInfo.js` |
| двинуть/телепортировать токен, подсветить его | §5.7 | 575–589 | `dead_or_alive`, `PackTacticsCheck` |
| выбрать цель и атаковать из кода, фильтры «кто может» | §5.8–5.9 | 590–614 | `attack-of-opportunity` |
| создать бой, добавить участников, передать ход | §6 | 615–645 | `enemy_spoted`, `deepVoyager` |
| хранить состояние и не сработать дважды | §7 | 646–662 | таблица §7 |
| чат-карта способности, whisper, тосты | §8 | 663–691 | `Indefatigable_endurance` |
| датасет JSON+fetch, плейлисты, FXMaster, тайлы, тьма | §9 | 692–741 | `weather_by_day_time` |
| ИИ / внешний HTTP API, глобальный объект для макросов | §10 | 742–775 | `deepVoyager` |
| **мелкие хитрости — прочитать обязательно** | §11 | 776–798 | — |
| **грабли: что не копировать** | §12 | 799–822 | — |
| готовые рецепты А–З под новую способность | §13 | 823–851 | — |
| релиз, версии, граф знаний | §14 | 852–867 | `release.ps1` |
| найти механику, которой **нет** в `extensions/` (она в данных) | §15 | 868–888 | Folder «Программирование», `temp/dump/analysis.txt` |
| «использовал предмет → выполнился скрипт» без расширения | §15.1 | 889–937 | `[postActiveEffects]ItemMacro` в «Помощь» / «Толчок» |
| дать бонус / преимущество / статус чистыми данными | §15.2 | 938–959 | Сон (`flags.dnd5e.condition`), Благословение (`1d4`) |
| авто-снятие эффекта по ходу боя + «включатель» | §15.3–15.4 | 960–992 | Отступление, Уклонение, `activate_effect` |
| аура с уроном/спасброском каждый ход | §15.5 | 993–1015 | Spirit Guardians (`OverTime` + `ActiveAuras`) |
| «рассыпал — и осталось на сцене» (тайл из шаблона) | §15.6 | 1016–1036 | Калтропы / Капкан / Металлические шарики |
| кнопка действия без описания и эффектов | §15.7 | 1037–1052 | «Взаимодействие с НПС», «Рывок» |
| не сломать происхождение предмета (клоны, сцены) | §15.8 | 1053–1075 | `flags.core.sourceId`, `flags.dnd5e.dependents` |
| данные или код: куда положить механику | §15.9–15.10 | 1076–1122 | таблица §15.10 |
| снять такие же данные с живого мира | §15.11 | 1123–1143 | `temp/cdp.py`, `temp/probe5.py` |

### 0.2 Почему «не работает» — проверить сначала (4 частые причины)

1. Независимый блок стоит **после** `return` в другом блоке — молча не выполняется (§12, поз.1).
2. Захардкоженные id сцены/токена/актёра/файла картинки — «протухли» после дублирования (§12, поз.2 и 8).
3. Нет GM/owner-guard — логика проходит на каждом клиенте, диалоги дублируются (§12, поз.5).
4. Механика реализована **в данных предмета** (`onUseMacroName` + `flags.dae.macro`), а не в `extensions/`
   — в коде модуля её искать бесполезно (§15.1); и наоборот: у «Убежище» она есть в **обоих** местах.

---

## 1. Каркас фреймворка (как вообще всё живёт)

```
biyk_ext/
├── module.json        # esmodules: ["main.mjs", "settings.mjs"]
├── main.mjs           # Hooks.once('ready') → loadExtensions()
├── settings.mjs       # Hooks.once('init') → по EXTENSIONS регистрирует чекбоксы
├── registry.js        # EXTENSIONS = { "<папка>": { label, reload } }
└── extensions/<name>/index.js   # ОБЯЗАТЕЛЬНЫЙ экспорт: export function init()
```

Загрузка — динамический `import()` только включённых расширений:

```javascript
const enabledSettings = Object.keys(EXTENSIONS).filter(key => game.settings.get('biyk_ext', key));
for (const ext of enabledSettings) {
    if (!game.biyk_ext.extensions[ext]) {
        const mod = await import(`./extensions/${ext}/index.js`);
        game.biyk_ext.extensions[ext] = mod;
        mod.init?.();
    }
}
```

**Чек-лист «добавить новую способность»:**

1. Создать `extensions/<my_feat>/index.js` с `export function init()`.
2. Добавить в `registry.js` строку `"<my_feat>": { label: "Название", reload: true }`.
3. Больше ничего: настройка-чекбокс появляется автоматически (`settings.mjs`), билда нет.
4. Включить чекбокс в настройках модуля → перезагрузить мир.

Важно: `index.js` импортируется **один раз за сессию**, поэтому часть расширений
(`initiative-confirmation`) регистрирует `Hooks.on(...)` прямо на верхнем уровне файла —
это работает, но стиль «всё внутрь `init()`» безопаснее и единообразнее.

---

## 2. Точки входа — какие хуки уже используются и для чего

| Хук | Где применяется | Что даёт / можно отменить |
|---|---|---|
| `dnd5e.useItem` | ArcaneRecovery, DivineRecovery, EnhanceAbility, LesserRestoration, ProtectionFromPoison, activate_effect, blindness_deafness, possessed-items, stas_char, warlord_word | «предмет ИСПОЛЬЗОВАН» — основной способ навесить поведение на заклинание/черту |
| `dnd5e.preUseItem` | checkWizardComponents | `return false` **блокирует** использование (проверка компонентов/фокуса) |
| `dnd5e.preApplyDamage` | dead_or_alive | `return false` отменяет урон; вручную ставим HP=1 |
| `dnd5e.rollSkill` | goldBard, rage-extender | подмена результата броска навыка |
| `dnd5e.rollAbilityTest` | rage-extender | продление ярости на проверке Силы |
| `midi-qol.preAttackRoll` | avoid, protection_from_evil, sanctuary | мутируем `workflow.advantage / disadvantage`, `return false` отменяет атаку |
| `midi-qol.RollComplete` | battle_inspiration, warlord_help | после броска атаки: есть `workflow.hitTargets`, `attackRoll.total` |
| `midi-qol.DamageRollComplete` | guardian-shield | после расчёта урона, **до** применения: можно `workflow.targets.delete(token)` |
| `midi-qol.postDamageRollComplete` | removeInvisible, rage-extender, (Chaos Bolt) | урон уже применён |
| `midi-qol.postComputeCoverBonus` | sharp_shooter | мутируем `workflow.bonusAC` (бонус укрытия к КД) |
| `combatTurn` / `combatRound` / `combatTurnEnd` | PackTacticsCheck | начало/конец хода: навесить/снять временный эффект |
| `updateCombat` | deepVoyager | «движок» ИИ-ходов |
| `createCombat` | initiative-confirmation | старт боя → предложить способность |
| `preUpdateCombat` | combatDistance | смена раунда/остановка боя → чистка флагов |
| `preUpdateToken` | attack-of-opportunity, combatDistance | **до** перемещения: есть старые координаты + `updateData.x/y` |
| `updateToken` | enemy_spoted, removeInvisible, add-token-visions | **после** движения: ловим `updateData.x/y` |
| `targetToken` | PackTacticsCheck | выбор цели юзером → пересчёт «тактики стаи» |
| `createActiveEffect` / `deleteActiveEffect` | add-token-visions, removeInvisible | реакция на любое вешание/снятие эффекта |
| `preUpdateItem` | equipment-checker | проверка экипировки: `return false` + правка `system.system.equipped` отменяет надевание |
| `updateActor` | Indefatigable_endurance | HP упало → предложить реакцию «остаться на 1 HP» |
| `renderActorSheetV2` | renderActorSheet | прямо в DOM листа: спрятать/заблокировать элементы игрокам |
| `renderCombatTracker` | deepVoyager | инжект своей кнопки в трекер |
| `simple-calendar-date-time-change` | day_light, weather_by_day_time | привязка к игровому времени |
| `fxmaster.updateParticleEffects` (через `Hooks.call`) | weather_by_day_time | запуск погоды/частиц |

---

## 3. Паттерны создания способностей

### 3.1 «Использовали предмет X → сделай Y» (самый частый)

```javascript
export function init() {
    Hooks.on("dnd5e.useItem", async (item, config, options) => {
        if (!item.name.toLowerCase().includes("название способности")) return;
        const actor = item.actor ?? item.parent;
        // ... логика
    });
}
```

Хитрости из кодовой базы:
- **Поиск по имени — толерантный к локализации и регистру**:
  `item.name.toLowerCase().includes("enhance ability") || item.name.toLowerCase().includes("усиление способности")` (EnhanceAbility);
  `["ярость", "rage"]`, `["тактик"+"стаи", "pack tactics"]` (PackTacticsCheck, rage-extender).
- **Цели брать из двух мест** (важно для NPC и для запуска из макроса):

```javascript
let targets = [];
if (config?.targets && config.targets.size) targets = Array.from(config.targets);
else if (game.user.targets.size) targets = Array.from(game.user.targets);
```

- **Точное равенство имени** — если способность авторская и название гарантированно одно:
  `if (item.name !== "Власть над предметом") return;` (possessed-items).

### 3.2 Создание ActiveEffect из кода (бафф/дебафф)

Проверенный шаблон (EnhanceAbility, PackTacticsCheck):

```javascript
const effectData = {
    label/name: "Бычья сила (Enhance Ability)",
    icon: "icons/svg/upgrade.svg",
    origin: sourceItem.uuid,           // или actor.uuid — «кто источник»
    disabled: false,
    duration: {
        seconds: convertToSeconds(duration, durationUnit),
        startTime: game.time.worldTime,
        rounds: 1, startRound: game.combat?.round, startTurn: game.combat?.turn
    },
    flags: {
        core: { statusId: "bullsStrength" },     // иконка-статус на токене
        dnd5e: { effectType: "spell" },
        dae: { specialDuration: ["turnEnd"], stackable: false }  // авто-снятие (нужен DAE)
    },
    changes: [
        { key: "flags.dnd5e.advantage.ability.check.str", mode: CONST.ACTIVE_EFFECT_MODES.ADD, value: 1, priority: 20 },
        { key: "flags.midi-qol.advantage.attack.all",     mode: CONST.ACTIVE_EFFECT_MODES.OVERRIDE, value: true, priority: 20 },
        { key: "system.attributes.hp.temp",               mode: CONST.ACTIVE_EFFECT_MODES.OVERRIDE, value: tempHPValue },
        { key: "system.abilities.str.carryMultiplier",    mode: CONST.ACTIVE_EFFECT_MODES.OVERRIDE, value: 2 }
    ]
};
await actor.createEmbeddedDocuments("ActiveEffect", [effectData]);
```

Ключевые `key`, которые реально используются:
- `flags.dnd5e.advantage.ability.check.<str|dex|int|wis|cha|con>` и `...ability.save.<...>` — преимущество на проверки/спасброски;
- `flags.dnd5e.advantage.attack.all`, `flags.midi-qol.advantage.attack.all` — на атаки;
- `system.attributes.hp.temp` — временные HP (закатить результат `new Roll("2d6")`);
- `system.abilities.str.carryMultiplier` — грузоподъёмность (через DAE).

**Обязательный утилитарий** (god-node проекта, 7 связей):

```javascript
function convertToSeconds(duration, unit) {
    if (duration === 0) return 0;
    switch (unit.toLowerCase()) {
        case "round":  return duration * 6;
        case "minute": return duration * 60;
        case "hour":   return duration * 3600;
        case "day":    return duration * 86400;
        default:       return duration;
    }
}
```

Длительность брать из самого предмета: `item.system.duration?.value` + `item.system.duration?.units`.

### 3.3 Навешивание/снятие стандартного статуса (condition)

```javascript
// Blinded/Deafened из системы (blindness_deafness)
const blindedEffect = CONFIG.statusEffects.find(e => e.name === "Blinded");
if (!blindedEffect._id) blindedEffect._id = foundry.utils.randomID();   // фикс для CE-эффектов
await token.toggleEffect(blindedEffect, { active: true });
```

Снятие одним проходом по эффектам (LesserRestoration, ProtectionFromPoison):

```javascript
for (let effect of game.user.targets.first().actor.effects) {
    if (effect.name.toLowerCase() === 'poisoned') return await effect.delete();
}
```

Активация уже существующего, но «выключенного» эффекта предмета — `activate_effect`:

```javascript
let allEffects = [
    ...actor.effects.contents,
    ...actor.items.reduce((acc, i) => acc.concat(i.effects.contents), [])
];
let targetEffect = allEffects.find(e => e.name.includes(itemName));
if (targetEffect?.disabled) await targetEffect.update({ disabled: false });
```

**Общее правило поиска эффекта** — смотреть и `label`, и `name`, и `flags.core.statusId`
(removeInvisible, rage-extender):

```javascript
const found = actor.appliedEffects.find(e => {
    const label = e.label?.toLowerCase() || "", name = e.name?.toLowerCase() || "";
    return RAGE_EFFECT_NAMES.some(n => label.includes(n) || name.includes(n))
        || e.flags?.core?.statusId === "invisible";
});
```

### 3.4 Реакции: «можно ли ещё реагировать» и трата реакции

Единый механизм — флаг `midi-qol.actions` на актёре (battle_inspiration, warlord_help, guardian-shield):

```javascript
const currentRound = game.combat?.round ?? 0;
const midiActions = actor.getFlag("midi-qol", "actions") || {};
if (midiActions.reaction?.round === currentRound) return;   // уже потрачена

await actor.setFlag("midi-qol", "actions",
    foundry.utils.mergeObject(midiActions, { reaction: { round: currentRound } }));
```

Более «правильная» проверка с деградацией (attack-of-opportunity):

```javascript
let canReact = true;
if (game.modules.get("midi-qol")?.active && game.midiqol?.canUseReaction) {
    canReact = game.midiqol.canUseReaction(actor);
} else if (actor.flags?.["midi-qol"]?.reactionUsed === true) {
    canReact = false;
}
```

Расход зарядов предмета: `await item.update({ "system.uses.value": currentUses - 1 })`.

### 3.5 Вмешательство в бросок атаки/урона (мутируем workflow)

```javascript
Hooks.on("midi-qol.preAttackRoll", async (workflow) => {
    if (!workflow.item?.system?.actionType) return true;      // не атака оружием — не трогаем
    for (let targetToken of workflow.targets) {
        const eff = targetToken.actor.appliedEffects.find(e => e.name.toLowerCase().includes("уклонение"));
        if (!eff) continue;
        if (workflow.advantage)      { workflow.advantage = false; workflow.disadvantage = false; }
        else                         { workflow.disadvantage = true; }
    }
    return true;
});
```

Что уже мутировали в проекте:
- `workflow.advantage / disadvantage` (avoid, protection_from_evil);
- `workflow.bonusAC` — бонус укрытия (sharp_shooter);
- `workflow.targets.delete(token)` — снять цель с получателей урона (guardian-shield);
- отмена атаки: `workflow.attackRoll = null; workflow.damageRoll = null; return false;` (sanctuary).

Повторная проверка попадания после добавления кубика (warlord_help):

```javascript
const newAttackTotal = workflow.attackRoll.total + d4Roll.total;
const AC = targetActor.system.attributes.ac.value;
if (newAttackTotal >= AC) {
    await MidiQOL.applyTokenDamage(
        [{ damage: workflow.damageTotal, type: workflow.defaultDamageType }],
        workflow.damageTotal, new Set([targetToken]),
        workflow.item?.uuid, new Set(), { workflow }
    );
}
```

### 3.6 Спасброски, DC, opposed-проверки

```javascript
// Спасбросок цели против DC заклинателя (possessed-items)
const spellDC = casterActor.system.attributes.spelldc;
const saveRoll = await targetActor.rollAbilitySave("str", { chatMessage: true });
if (saveRoll.total >= spellDC) { /* цель resistнула */ }

// DC из предмета (blindness_deafness): item.system.save.dc
// Свой расчёт DC: 8 + prof + mod (sanctuary)
// Противопоставление через кастомные Roll (enemy_spoted):
const playerRoll = await new Roll(`1d20 + ${stealthBonus}`).evaluate();
const npcRoll    = await new Roll(`1d20 + ${perceptionBonus}`).evaluate();

// Простейший ролл с асинхронностью (removeInvisible, EnhanceAbility)
const roll = await new Roll("1d6").roll({ async: true });
await roll.toMessage({ flavor: "..." });
```

Бонки навыков брать с фолбэком:
`actor.system.skills?.ste?.total ?? actor.system.skills?.ste?.mod ?? 0`.

### 3.7 Ячейки заклинаний и ресурсы-очки

Прямое чтение/запись ячеек (ArcaneRecovery, DivineRecovery, stas_char):

```javascript
const slotKey = `spell${level}`;                       // 'spell1'...'spell5'
const used = actor.system.spells[slotKey]?.value || 0; // value = СКОЛЬКО ИСПОЛЬЗОВАНО
const max  = actor.system.spells[slotKey]?.max  || 0;
await actor.update({ [`system.spells.${slotKey}.value`]: used + count });
```

Лимит восстановления: `Math.ceil(classLevel / 2)`, для жреца ещё `Math.min(..., wis.mod)`.
Уровень класса: `actor.items.find(i => i.type === "class" && i.name.toLowerCase().includes("волшебник")).system.levels`.

**Трюк «заклинание не тратит ячейку» (stas_char)** — предварительно **увеличить** счётчик
использования на 1, чтобы штатный расход вернул значение к исходному:

```javascript
await actor.update({ [`system.spells.${spellLevel}.value`]: slots.value + 1 });
// ... и списать очки с предмета-ресурса:
await actor.items.get(resourceItem.id).update({ 'system.uses.value': currentPoints - cost });
```

Ресурс как «пул очков» — обычный предмет с `system.uses.value/max` ищется по имени
(`actor.items.find(i => i.name === 'Очки чар')`).

Фильтрация «не трогать кантрипы/подготовленные»: `item.type !== "spell"`, `item.system.level === 0`,
`item.system.preparation.mode === "pact"`.

### 3.8 Сбор «доступных действий» существа (для ИИ/меню)

Готовый рецепт из deepVoyager (`utils/help.js#buildItemAction`):

```javascript
for (let item of token.actor.items) {
    if (((item.type === "weapon" || item.type === "equipment") && item.system.equipped)
        || item.type === "spell" || item.type === "consumable") {
        availableActions.push(buildItemAction(item));
    }
    if (item.type === "feat" && item.effects?.size) {
        for (let effect of item.effects) availableFeats.push({ name: effect.name, enabled: !effect.disabled });
    }
}
availableActions.sort((a, b) => (a.type === "weapon" && b.type !== "weapon") ? -1 : 1);
```

Описание для промпта очищается от HTML и компендиум-ссылок и режется до 200 символов:

```javascript
item.system.description?.value
    ?.replace(/<[^>]+>/g, "")
    ?.replace(/@Compendium\[[^\]]+\]\{[^}]+\}/g, "")
    ?.replace(/\[\/[^\]]+\]/g, "")
    ?.replace(/[\n\r]+/g, " ")?.trim()?.substring(0, 200)
```

Состояние по HP — дешёвая «абстракция» для ИИ/сообщений: `getStatus(actor)` →
`мертв / тяжело ранен / ранен / здоров` (пороги 0 / 33% / 66%).

---

## 4. UI-приёмы

### 4.1 Диалог с выбором варианта (radio) → Promise

Канон (EnhanceAbility, blindness_deafness):

```javascript
const choice = await new Promise(resolve => {
    new Dialog({
        title: "Выберите эффект",
        content: `<label><input type="radio" name="effectChoice" value="bullsStrength" checked> ...</label>`,
        buttons: {
            ok:     { label: "Применить", callback: html => resolve(html.find('input[name="effectChoice"]:checked').val()) },
            cancel: { label: "Отмена",    callback: () => resolve(null) }
        },
        default: "ok"
    }).render(true);
});
if (!choice) return;
```

### 4.2 Диалог-подтверждение для реакции

```javascript
const useReaction = await Dialog.confirm({
    title: abilityName,
    content: `<p><b>${actor.name}</b>, оставить 1 HP? Осталось использований: ${usesRemaining}</p>`,
    defaultYes: false            // важно: реакция по умолчанию «нет»
});
```

`Dialog.wait` + динамические кнопки, когда вариантов N (attack-of-opportunity — выбор оружия,
guardian-shield/Chaos Bolt — выбор второй цели):

```javascript
const buttons = {};
for (const w of weapons) buttons[w.id] = { icon: '<i class="fas fa-fist-raised"></i>', label: w.name, callback: async () => {...} };
buttons.cancel = { icon: '<i class="fas fa-times"></i>', label: "Отмена" };
new Dialog({ title, content, buttons, default: "cancel" }).render(true);
```

### 4.3 Живая валидация суммы внутри диалога (ArcaneRecovery)

В `render()` вешаем слушатель на `input[type=number]` и пересчитываем `Σ level × count`,
подкрашивая превышение лимита:

```javascript
render: (html) => {
    const inputs = html.find('#slots input[type="number"]');
    const updateSum = () => {
        let sum = 0;
        inputs.each((i, el) => sum += parseInt($(el).data('level')) * parseInt($(el).val()));
        const out = html.find('#recovery-sum-output');
        out.html(`Выбрано: <b>${sum}</b> (из ${max})`);
        out.css('color', sum > max ? 'red' : 'inherit');
    };
    inputs.on('change keyup', updateSum);
    updateSum();
}
```

Обработка — отдельно (`_handle...`): собрать `updates`-объект, проверить лимит,
`await actor.update(updates)`, иначе `ui.notifications.error` + `return false`.

### 4.4 Автозакрытие диалога по таймауту (не блокировать ход)

```javascript
setTimeout(() => { if (dialog.rendered) dialog.close(); }, 10000);
```

### 4.5 Инжект кнопки в интерфейс + состояние в localStorage (deepVoyager/messageBox)

```javascript
Hooks.on("renderCombatTracker", () => addGMButton());   // переставляем после каждого рендера
// внутри addGMButton: guard по id, insertAdjacentElement, data-tooltip, обработчик клика
const savedText = localStorage.getItem("gmNotes") || "";
localStorage.setItem("gmNotes", newText);
```

### 4.6 Резать лист персонажа игрокам (renderActorSheet)

```javascript
Hooks.on("renderActorSheetV2", (app) => {
    if (!app.actor) return;
    if (game.user.isGM) return;
    document.getElementsByClassName('sheet-header-buttons')[0].style.display = 'none';
    document.querySelectorAll('section.currency input,button').forEach(i => i.disabled = true);
});
```

---

## 5. Геометрия, токены, движение, линия видимости

### 5.1 Поймать перемещение

```javascript
Hooks.on("preUpdateToken", async (tokenDoc, updateData, options, userId) => {
    if (updateData.x === undefined && updateData.y === undefined) return;   // не двигался
    const moved = (updateData.x ?? tokenDoc.x) - tokenDoc.x;                 // «было → станет»
});
Hooks.on("updateToken", async (tokenDoc, updateData, options, userId) => {
    if (updateData.x === undefined && updateData.y === undefined) return;
    const user = game.users.get(userId);
    if (!user || user.isGM) return;                 // реагируем только на ход игрока
});
```

### 5.2 Расстояние: 4 способа из кодовой базы

| Задача | Приём |
|---|---|
| футы между токенами (Midi-QOL) | `MidiQOL.getDistance(a, b, false)` |
| клетки/футы по сетке | `canvas.grid.measureDistance(tokenA, tokenB)` |
| точный путь по ray | `const ray = new Ray(prev, next); canvas.grid.measureDistances([{ray}], { gridSpaces: true })[0]` |
| грубый пиксельный радиус | `Math.hypot(a.center.x-b.center.x, a.center.y-b.center.y)` и `(feet/5)*canvas.grid.size` |

Формула перевода футов в клетки: `Math.max(1, Math.floor(reachFeet / 5))`.

### 5.3 Chebyshev-расстояние по занимаемым клеткам (для reach)

```javascript
function getOccupiedCells(t) {
    const gs = canvas.grid.size;
    const c1 = Math.floor(t.x/gs), r1 = Math.floor(t.y/gs);
    const c2 = Math.floor((t.x + t.w - 1)/gs), r2 = Math.floor((t.y + t.h - 1)/gs);
    const cells = [];
    for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) cells.push({ r, c });
    return cells;
}
// минимальная клеточная дистанция = min по max(|dr|,|dc|)
```

### 5.4 Проверка коллизий/проходимости — тройной фолбэк по версиям

```javascript
const movementBackend = CONFIG.Canvas.polygonBackends?.movement;   // 1. V11+
if (movementBackend?.testCollision) collision = movementBackend.testCollision({
    type: "movement", object: token, source: new PIXI.Rectangle(x, y, token.w, token.h), mode: "any" });
else if (typeof token.document?.checkCollision === "function")     // 2. V10+
    passable = await token.document.checkCollision(x, y, { mode: "move" });
else if (canvas.walls?.checkCollision)                             // 3. legacy ray
    collision = canvas.walls.checkCollision(new Ray(from, to), { type: "move", mode: "any", object: token });
```

### 5.5 Видимость / Line of Sight (LOS)

```javascript
const collision = canvas.walls.checkCollision(new Ray(a, b), { type: "sight", mode: "any" });
const canSee = MidiQOL.canSense
    ? MidiQOL.canSense(t.document, target.document)
    : canvas.sight.testVisibility(t, { object: target });
```

Занятость клетки живым токеном — пересечение bounding box (deepVoyager/move.js):

```javascript
const occupied = canvas.tokens.placeables.some(t =>
    t.id !== token.id &&
    (t.actor?.system?.attributes?.hp?.value ?? 0) > 0 &&
    t.x < bounds.x + bounds.width && t.x + t.w > bounds.x &&
    t.y < bounds.y + bounds.height && t.y + t.h > bounds.y);
```

### 5.6 «Роза движения» для ИИ — сколько клеток свободно в 8 направлениях

`getMovementRose(token)` → `{ up, upRight, right, ... }` — в каждом направлении шагами до
упора проверяем `canMoveTo` и границы сцены (`canvas.dimensions.width/height`). Готово, переиспользуй.

### 5.7 Двигать/телепортировать токен

```javascript
await token.document.update({ x, y }, { animate: true });              // с анимацией
await token.document.update({ x, y }, { animate: false, teleport: true }); // мгновенно (смерть/респаун)
await new Promise(r => setTimeout(r, 500));                            // «синхронизация» после движения
```

Мигание-подсветка при навешивании эффекта (PackTacticsCheck):

```javascript
if (token?.isVisible) token.animate({ attribute: "alpha", to: 0.5, duration: 200 })
    .then(() => token.animate({ attribute: "alpha", to: 1.0, duration: 200 }));
```

### 5.8 Взять/сменить цели программно и атаковать (атака по возможности)

```javascript
await game.user.updateTokenTargets([targetToken.id]);
await new Promise(r => setTimeout(r, 50));
await item.use({ target: [targetToken] });
```

### 5.9 Свой набор фильтров «кто может атаковать/помочь»

```javascript
canvas.tokens.placeables.filter(t => {
    if (!t.actor) return false;
    if (t.actor.system.attributes.hp.value <= 0) return false;              // живые
    if (t.document.disposition !== attackToken.document.disposition) return false;  // союзники
    return game.user.isGM || t.actor.isOwner;                              // кому принадлежат
});
```

Тип существа читаем цепочкой фолбэков (protection_from_evil):
`system.details.type.value` → `data.data.details.type` → `system.traits.creatureType`,
сравнивая со списком и на английском, и на русском.

---

## 6. Бой, инициатива, автоматический ход

```javascript
// Создание/пополнение боя без ручного «старта» (enemy_spoted)
let combat = game.combat;
if (!combat || combat.scene?.id !== canvas.scene.id) combat = await Combat.create({ scene: canvas.scene.id });
const existing = new Set(combat.combatants.map(c => c.tokenId));
const toAdd = tokens.filter(t => !existing.has(t.id)).map(t => ({ tokenId: t.id, sceneId: scene.id }));
await combat.createEmbeddedDocuments("Combatant", toAdd);
if (ui.combat) ui.combat.render();     // форсируем перерисовку трекера (лечит combat-tracker-dock)

// Передать ход (deepVoyager, после паузы на анимации)
await new Promise(r => setTimeout(r, 5000));
game.combat.nextTurn();
```

Учёт запаса движения на токене через флаги (combatDistance):

```javascript
Hooks.on("combatTurn", async (combat, combatant) => {
    await tokenDoc.setFlag("world", "normalRemaining", baseSpeed);
    await tokenDoc.setFlag("world", "dashBonus", baseSpeed);
});
// в preUpdateToken: сначала тратим normal, потом dash; по исчерпании — ui.notifications.warn
Hooks.on("preUpdateCombat", async (combat, change) => {   // сброс при смене раунда/остановке
    if (change.round || change.active === false) for (const c of combat.combatants) await c.token.unsetFlag("world", "normalRemaining");
});
```

---

## 7. Хранение состояния и защита от «двойных срабатываний»

| Приём | Пример | Код |
|---|---|---|
| Флаг на токене/акторе/сцене | combatDistance, currency-watcher, dead_or_alive | `doc.setFlag("world", "key", value)` / `getFlag` / `unsetFlag` |
| Guard-флаг «уже обработали» + автосброс | dead_or_alive | `if (await actor.getFlag("world","playerDeathProcessed")) return; await actor.setFlag(..., true); setTimeout(() => actor.unsetFlag(...), 2000);` |
| Дедуп-флаг хука | enemy_spoted | `if (token.flags?.biyk_ext?.dnd5eAoO) return; token.flags.biyk_ext = {dnd5eAoO: true};` |
| Троттлинг по времени (per-user) | enemy_spoted, deepVoyager | `const last = map.get(user.id) || 0; if (Date.now() - last < 1000) return; map.set(user.id, Date.now());` или `COMBAT_TURN_THROTTLE = 5000` |
| Мьютекс на обработку | enemy_spoted | `if (isProcessing) return; isProcessing = true; try {...} finally { isProcessing = false; }` |
| Ключ «уже делали» | weather_by_day_time | `const key = \`${journeyDay}-${tod}\`; if (key === lastKey) return; lastKey = key;` |
| Защита от рекурсии в updateActor | Indefatigable_endurance | перед `actor.update(...)` передавать маркер: `{relentless: true}` и/или сравнивать старое/новое значение |
| localStorage | deepVoyager GM-заметки | `localStorage.getItem/setItem("gmNotes", ...)` |

Обязательная проверка значения, а не факта записи: `if (updateData?.system?.attributes?.hp?.value === undefined) return;`

---

## 8. Сообщения, чат-карты, уведомления

```javascript
// Стандартная «карточка способности»
ChatMessage.create({
    speaker: ChatMessage.getSpeaker({ actor }),       // или { token }
    content: `
        <div class="dnd5e chat-card">
            <header class="card-header flexrow">
                <img src="${abilityItem.img}" title="${abilityItem.name}" width="36" height="36"/>
                <h3 class="item-name">${abilityItem.name}</h3>
            </header>
            <div class="card-content"><b>${actor.name}</b> ... </div>
        </div>`
});

// Только ГМ
ChatMessage.create({ content, whisper: [game.user.id] });
ChatMessage.create({ content, whisper: ChatMessage.getWhisperRecipients("GM") });
ChatMessage.create({ content, speaker: { alias: "Погода и атмосфера" }, whisper: [game.user.id] });

// Тосты
ui.notifications.info/warn/error("...");
```

Богатый HTML-отчёт (weather_by_day_time): `<article><h3>дата — пора</h3><p><strong>Локация:</strong> ...</p><hr><p><em>notes</em></p></article>` из полей датасета.

---

## 9. Данные как контент (JSON/CSV) и интеграции

**Шаблон «датасет + fetch»** (weather_by_day_time):

```javascript
async function getPlaylists() {
    const resp = await fetch("modules/biyk_ext/extensions/weather_by_day_time/data/playlist.json");
    return await resp.json();
}
// кэш в модуле: let calendar = null; getCalendar() заполняет один раз
```

Плюс офлайн-генерация `calendar.json` из `events.csv` + `locations.csv` скриптом
`scripts/gen_calendar.py`; путь к арту хранится в data как `modules/.../images/N.png`.

**Playlists API** (создание/синхронизация):

```javascript
let folder = game.folders.find(f => f.name === "Дорога" && f.type === "Playlist");
if (!folder) folder = await Folder.create({ name: "Дорога", type: "Playlist" });
await Playlist.create({ name, folder: folder.id, sounds });                       // v11/v12
await playlist.createEmbeddedDocuments("PlaylistSound", [{ name, path }]);       // adding
for (const sound of playlist.sounds) await sound.delete();                        // removing
await pl.stopAll(); await target.playAll();
```

Хитрости: URL-энкодинг путей (`path.replace(/&/g,'%26')`), валидация расширения файла
(`["mp3","ogg","wav","flac","m4a","webm"]`) с удалением «протухших» записей,
лог предупреждения при `&` в пути.

**FXMaster:** `Hooks.call("fxmaster.updateParticleEffects", effects);`

**Simple Calendar:** хук `simple-calendar-date-time-change` + `await SimpleCalendar.api.getCurrentDay()`
(для `numericRepresentation`), свои вычисления «дня пути» через кумулятивные смещения месяцев Harptos.

**Своя сцена/тайл:**

```javascript
const roadScene = game.scenes?.get(SCENE_ID);
const tile = roadScene.tiles?.get(TILE_ID);
if (tile.texture?.src !== img) await tile.update({ "texture.src": img });
if (game.scenes.active?.id === roadScene.id) await canvas.draw();
// затемнение: scene.update({ darkness }) c порогом |Δ| > 0.05, globalLight!==undefined
```

**Socket/IPC (info.js):** эмит от игрока и подписка на стороне ГМ + `Hooks.callAll("combatTurn", ...)` —
способ переложить логику, живущую у ГМа, на действие игрока.

---

## 10. ИИ-подсистема (deepVoyager) как отдельный класс решений

Структура: `extensions/deepVoyager/{index.js, actions/*, utils/*}` с нормальными ESM-импортами
(`import {move} from "./actions/move.js"`). Это единственный подпроект из нескольких файлов, всё остальное — один файл.

Конвейер хода:

```
собрать данные (позиция/скорость/статус/языки/disposition)
  → friends/enemies/neutrals по disposition
  → availableActions (buildItemAction) + availableFeats + movement (getMovementRose)
  → getAction(data)  // fetch http://localhost:9999/ask, prompt по disposition
  → parseResponse → [{action:'move'|'use'|'target'|'message', conf}]
  → исполнение с лимитами: limit = { move: baseMove, use: 1, bonus: 1, target: 1 }
  → game.combat.nextTurn()
```

Перенятия:
- **Командный протокол вместо JSON** — парс regex-ом, устойчив к болтовне модели:
  `/(move|use|target|message)\/([^\n]+)$/gm` → `move/up`, `use/<itemId>`, `target/<id>`, `message/<lang>/<текст>`.
  Ответ доставать цепочкой: `response.response || response.text || response.content || response.answer`.
- **Нечёткое совпадение ID** (`similarity()` — Левенштейн, порог `> 0.87`) — потому что модель
  «галлюцинирует» значения идентификаторов.
- **Фолбэк, если ИИ ошибся**: move не удался → искать предмет «рывок», звать `/path` endpoint
  и идти по шагам пути, прерываясь на блоке.
- **Разделение по ролям**: `disposition === -2` (босс/ГМ-персонаж) → ИИ только советует,
  окно для ГМа; обычные NPC → ИИ играет сам.
- **Глобальный API для макросов**: `game.modules.get("biyk_ext").api = api;` — потом из консоли/макроса
  `game.modules.get('biyk_ext').api.testPath()`.
- **Комментарий-якорь** в важном месте: `// ВАЖНО: fetch к нейросети ДЛЯ ВСЕГДА оставляем, не удалять!`
- **Мёртвый код под `if (0) { ... }`** — черновик способности (Chaos Bolt) лежит рядом, не мешая исполнению.

---

## 11. Мелкие хитрости, которые стоит переиспользовать

- Префикс в логах: `const LOG_PREFIX = "[WeatherByDayTime]"` / `const PREFIX = "⚔️[Щит Хранителя]"`
  и `DEBUG`-флаг с обёрткой `function log(...a){ if (DEBUG) console.log(...) }`.
- Распечатка аргументов хука в консоль при отладке (`console.log(item, config, options)`) —
  сигнатуры в dnd5e/midi-qol меняются, это самый быстрый способ их узнать.
- `const isDM = () => game.user.isGM; if (!isDM()) return;` — **все** «мировые» хуки начинаются с GM-guard'а,
  иначе логика выполнится на каждом клиенте и диалоги продублируются.
- Проверка зависимого модуля: `if (!game.modules.get("midi-qol")?.active) { console.error(...); return; }`
  и «тихий» фолбэк, если API нет: `game.midiqol?.canUseReaction`, `MidiQOL.canSense ? ... : ...`.
- Опциональная цепочка почти везде: `actor.system.attributes?.hp?.value ?? 0` — переживает смену схемы системы.
- Двойное чтение из новых и старых полей: `system.spells` vs `data.data...` (protection_from_evil, sanctuary).
- Реплика в чат как «сигнал игроку» вместо модалки (combatDistance, deepVoyager) — `whisper: [game.user.id]`.
- `token.animate(...)`, `canvas.draw()`, `ui.combat.render()` — три способа «обновить картинку» без перезагрузки.
- Предотвращение «двойного» лечения: `Math.min(value + heal, max)`; `Math.max(0, used - 1)`.
- Извлечение кубика хитов из строки: `hitDice.match(/d(\d+)/)`, иначе перебор `Object.values(actor.classes)` и `Math.max(...)`.
- Подмена результата броска через разбор строки: `roll.result.split(' ')`, правка минимума, `eval('nrt = '+str)`,
  `roll.toMessage = null` (goldBard) — **работает, но хрупко**: держи как запасной вариант.
- Wake-lock «не гаси экран» на загрузке (`main.mjs`) + баннер-заглушка + смена текста каждые 30 с,
  в конце `loadExtensions()` показывает `Загружено за N с`.

---

## 12. Известные грабли (не повторять / починить при случае)

1. **`return` в середине обработчика** съедает последующие блоки — именно так дорога не переключалась
   в `weather_by_day_time`, пока блок тайла висел после музыкальных `return`. **Правило:** независимые
   эффекты ставь **до** блоков с ранними выходами.
2. **Захардкоженные ID** (`q2be0cq4lQvHr2KS`, `Y13np4o1dLgdjHpn`, `5pNGL93cGjOtmjkU`, `ocnaVUdPmSkjKizF`,
   координаты респауна 1656/3528) — молча ломаются после дублирования сцены. Либо вынести в настройки,
   либо искать по имени + `console.warn`, когда не нашло.
3. **`currency-watcher/index.js`** вообще не имеет `init()` и ссылается на глобалы (`speaker`, `args`) —
   это заготовка под макрос, а не расширение; вызов из `loadExtensions()` его не запускает.
4. **Конфликт затемнения:** `day_light` и `weather_by_day_time` оба пишут `scene.darkness` по одному хуку.
   Если включены оба — они дерутся за один и тот же параметр.
5. **Отсутствие owner-guard** в части хуков → срабатывание на каждом клиенте и дубли диалогов
   (частично лечится `if (!isDM()) return;` / `actor.isOwner`).
6. **Устаревший API** местами: `actor.data.data...` (sanctuary, warlord_word), `workflow._advantage`,
   `roll.evaluate({async:true})` vs `evaluate()`.
7. `await token.actor?.appliedEffects; await game.actors.get(...)` в `use.js` — бесполезные `await`
   «для синхронизации»; лучше `await new Promise(r => setTimeout(r, N))` там, где реально нужен tick.
8. Ненайденные файлы картинок в данных (`images/7.png` отсутствует, нет 36–58) — код отрабатывает, визуально тишина.
   Проверять существование арта при генерации датасета.
9. `useItem` **после** расхода ячейки: если способность надо отменить — только `dnd5e.preUseItem` + `return false`.

---

## 13. Мини-рецепты (копипаст-основа)

**А. Пассивная черта (feat) «если на цели есть эффект X — атаки по ней с помехой»** → см. `avoid/index.js`
(хук `midi-qol.preAttackRoll`, `targetActor.appliedEffects.find(...)`, `workflow.disadvantage = true`).

**Б. Активная способность с выбором варианта и длительностью из предмета** → `EnhanceAbility/index.js`
(`dnd5e.useItem` → Dialog radio → `createXXXEffect()` → `createEmbeddedDocuments("ActiveEffect")`).

**В. Реакция союзника на событие (промах/урон по союзнику)** → `warlord_help/index.js` / `guardian-shield/index.js`
(фильтр `canvas.tokens.placeables` по disposition + дистанция + `midi-qol.actions` флаг + `Dialog.confirm` + `MidiQOL.applyTokenDamage`).

**Г. Реакция на собственное падение HP** → `Indefatigable_endurance/index.js`
(`updateActor`, сравнить `updateData?.system?.attributes?.hp?.value`, `abilityItem.system.uses.value`,
`actor.update({...}, {relentless: true})`, списать использование).

**Д. Кастомное заклинание с спасброском и переносом предмета** → `possessed-items/index.js`
(`spellDC`, `rollAbilitySave`, `weapon.toObject()` → `deleteEmbeddedDocuments("Item")` → `createEmbeddedDocuments("Item")`).

**Е. Счётчик-ресурс вместо ячеек («очки способностей»)** → `stas_char/index.js`
(`COST_TABLE[level]`, предмет-ресурс с `uses.value`, трюк «+1 к ячейке, чтобы не потратить»).

**Ж. Привязка к дате/времени и внешним данным** → `weather_by_day_time/index.js`
(fetch JSON, `lastKey`-дедуп, `journeyDay` из Harptos-смещений, FXMaster, playlist sync, tile/darkness).

**З. Новое расширение-подпроект с ИИ/внешним API** → `deepVoyager/*`
(actions/utils, registry-строка, `getAction`+`parseResponse`, лимиты действий, `game.modules.get('biyk_ext').api`).

---

## 14. Обслуживание и релиз

```powershell
powershell -File release.ps1     # patch+1 в module.json → module.zip → git commit+tag → gh release
graphify update .                # обновить граф знаний (AST-only, без стоимости API)
```

- `registry.js` — единственное место, где надо зарегистрировать расширение (label + reload).
- Перед чтением исходников по новой теме можно спросить граф: `graphify query "<вопрос>"`
  или открыть `graphify-out/GRAPH_REPORT.md` (309 узлов, 51 сообщество).
- Правила git: **не коммитить без явной команды** (см. `AGENTS.md`).
- Зависимости для данных `weather_by_day_time`: `pip install tinytag`; офлайн-скрипты в `scripts/`
  (`gen_calendar.py`, `download_music.py`, `curate_playlist.py`, `scan_disk.py`, `strip_metadata.py`, `batch_strip.py`).

---

## 15. Способности в ДАННЫХ: Item Macro + ActiveEffect + flags (data-driven)

Всё выше — про **код**. Значительная часть боевых механик этого мира живёт **в самих предметах**: в `flags`,
в `ActiveEffect.changes` и во встроенных макросах. Изучено снимком живого клиента через CDP
(мир `my`, dnd5e **3.3.1**): `temp/cdp.py` → `temp/probe5.py` → `temp/analyze.py`;
сырой дамп — `temp/dump/prog_items_full.json`, разбор — `temp/dump/analysis.txt`.

Источник-дерево: world-папка предметов `Folder.sI0X0y089nG8ciXu` **«Программирование»**, 4 подпапки, 27 предметов:

| Подпапка | id | Предметов | Типы |
|---|---|---|---|
| / (корень) | `sI0X0y089nG8ciXu` | 0 | — только контейнер |
| Заклинания | `kzRwzMR3PwZqa0mB` | 13 | spell 10, feat 2, weapon 1 |
| Предметы | `6onE4WwTU9SMtS9m` | 5 | consumable 5 |
| Способности | `8lAEAVla2a8Smrqj` | 3 | feat 3 |
| Способности для всех | `Y8mvOvo8skg5bXPN` | 6 | feat 4, spell 2 |

> **Иерархию папок читать только по `folder._source.folder`.** Геттеры `f.folder` / `f.parent` на живом V11
> возвращают `null` даже когда родитель есть (проверено: реальный parent — у 26 из 33 Item-папок).
> По DOM это видно сразу: `#sidebar .folder` в `items-sidebar` даёт вложенность корректно.

### 15.1 «Использовал предмет → выполнился код» без всякого расширения

Две половинки в данных одного предмета:

```
flags["midi-qol"].onUseMacroName = "[<хук>]ItemMacro"                      ← КОГДА (точка в workflow Midi-QOL)
flags.dae.macro / flags.itemacro.macro = {type:"script", scope:"global", command:"…"}  ← ЧТО (тело прямо в предмете)
```

Токен `ItemMacro` в конце имени = «макрос, встроенный в этот предмет», отдельный макрос-документ не нужен.
Реально встречающиеся хуки:

| Хук | Кто так делает | Что уже произошло |
|---|---|---|
| `preambleComplete` | Сон / Sleep* | цели определены, но эффект ещё не навешан — можно **отфильтровать цели** |
| `preActiveEffects` | Вкусные ягоды | перед применением эффектов — выдать/добавить предметы |
| `postActiveEffects` | Свет, Факел, Калтропы, Капкан, Шарики, Мультиатака, Помощь, Толчок, Стабилизация, Рога | эффекты применены — самый частый выбор |
| `isAttacked` | Убежище / Sanctuary * | по актёра цели пошли атакой — есть `workflow.attacker` |

Контекст внутри макроса: `actor`, `item`, `token`, `args`. Форма `args` зависит от хука:
- `pre/postActiveEffects`: `args[0]` ≈ workflow → `args[0].item / .actor / .workflow / .macroPass`;
- `isAttacked`: последний элемент `args[args.length - 1]` = `{tokenId, actorUuid, origin, workflow, …}`;
- ауры (`macro.itemMacro`): `args[0] === "on" | "off"`, `args[1]` = tokenId носителя, последний arg — `{tokenId, actorUuid, origin}`.

Отработанный пролог (Помощь / Толчок / Стабилизация — копипаст как есть):

```javascript
(async () => {
    const prefix = '[Shove] ';
    let itemContext, actorGm, workflow;
    try { itemContext = args[0]?.item; actorGm = args[0]?.actor; workflow = args[0]?.workflow; } catch (e) {}
    itemContext = itemContext || item;      // фолбэк на «чистый» запуск макроса
    actorGm = actorGm || actor;
    if (!actorGm || !itemContext) return console.log(prefix + 'no actor/item');
    const userToken = workflow.token;
    const targets = workflow.targets;       // Set document-ов цели
    // ... логика
})();
```

- `flags.dae.macro` и `flags.itemacro.macro` держат **одно и то же тело** (12 из 27 предметов с обоими).
  Правь в окне ItemMacro (DAE показывает ту же запись) — автосинхронизации между ними нет.
- Бросок из макроса — обычный API: `new Roll("1d20 + " + medMod).roll()` + `roll.toMessage(...)`,
  модификатор берётся из данных: `actorGm.system.skills.med.total`.
- Чужие модули дёргаются напрямую: `game.dfreds.effectInterface.toggleEffect("Torch", {uuids: [target.actor.uuid]})`
  (_macros_ «Свет» и «Факел» — ровно это одной строкой), `await fromUuid(uuid)`, `item.use()`.
- Мультиатака — оркестрация других предметов: `const ITEM_IDS = ["dZkOGqryX2ISj5m3", "7XXNlYbLHXHAsDTo", …];`
  `const WAIT_MS = 1000;` и последовательные `item.use()` с паузой (иначе Midi-QOL перемешает карточки).

### 15.2 Каталог `change.key` — что действительно читается из данных

Все 9 ключей, найденные в 27 предметах (mode/priority — как в дампе):

| key | mode | value | Пример (способность) |
|---|---|---|---|
| `system.bonuses.abilities.check` | 2 | `1d4` | Благословение |
| `system.bonuses.All-Attacks` | 2 | `1d4` | Благословение |
| `system.bonuses.abilities.save` | 2 | `1d4` | Сопротивляемость |
| `flags.midi-qol.advantage.all` | 5 | `1` | Решительность * (преимущество ко всем броскам) |
| `flags.midi-qol.advantage.ability.check.dex` | 5 | `true` | Уклонение |
| `flags.dnd5e.condition` | 5 | `"unconscious"` | Сон — **ставит состояние** без макроса |
| `system.attributes.movement.all` | 0 | `/2` | Spirit Guardians — режет скорость дробной формулой |
| `flags.midi-qol.OverTime` | 5 | см. §15.5 | урон/спасбросок по началу хода |
| `macro.itemMacro` | 0 | `@token @spellLevel @attributes.spelldc` | пробрасывает аргументы в Item Macro |

- Моды: **0 = OVERRIDE** (строка-формула, в т.ч. относительная `/2`), **2 = ADD** (кубик/число),
  **5 = SPECIAL** — для флагов, булев и строк (`"unconscious"` обязана быть в кавычках внутри значения).
- `priority: 20` стоит во всех изменениях — так DAE/Midi-QOL не перекрываются базовыми значениями системы.
- В `toObject()` поля `effectType` и иногда `priority` = `null`, а `change.id` = `null` — это нормально,
  документ домноляет их сам; не «чинить» руками.

### 15.3 Длительность: связка `duration` + `dae.specialDuration`

`specialDuration` работает **только при включённом DAE**; без него эффект висит до ручного снятия.

| `duration` | `dae.specialDuration` | `transfer` | `stackable` | Кто так делает |
|---|---|---|---|---|
| `{turns: 1}` | `["1Action"]` | true | multi | Решительность * |
| `{rounds: 1, seconds: 6}` | `["turnStart"]` | true | multi | Уклонение |
| `{startRound: 100}` | `["1Attack"]` | true | multi | Убежище (эффект-«маяк» на актёре) |
| `{rounds: 1, seconds: 60}` | `["isHit"]` | false | multi | Сон |
| `{turns: 1}` | `["turnEnd", "turnEndSource"]` | true | multi | Отступление |
| `{}` | `[]` | false | none | Spirit Guardians (aura, снимается концом концентрации) |

`stackable: "multi"` — допускается несколько копий (разные источники), `"none"` — одна, перезаписывает.
`duration.startRound: 100` — трюк «эффект практически бессрочный вне боя»: в бою снимается по `1Attack`,
а до боя висит на актёре и просто мешает.

### 15.4 Эффект-«носитель» с `disabled: true` + расширение `activate_effect`

Так делают «пассивности, которые включаются на ход» (Отступление):

1. В данных предмета лежит эффект с `disabled: true`, `specialDuration: ["turnEnd", "turnEndSource"]`,
   **без единого changes** — визуально это галочка-статус на листе.
2. `extensions/activate_effect/index.js` на `dnd5e.useItem` собирает `actor.effects.contents` +
   `actor.items.reduce(... i.effects.contents ...)`, ищет `e.name.includes(item.name)` и, если эффект
   `disabled`, делает `await targetEffect.update({disabled: false})`.
3. Дальше эффект «видят» другие расширения по имени: `attack-of-opportunity` ищет в `appliedEffects`
   `e.name.toLowerCase().includes("отступление")`, `avoid` — `"уклонение"`.

> **Ключевая неочевидность:** у таких эффектов `label` **пустой**, и имя выводится из предмета-источника
> (`origin`). Подпишешь эффект другим именем — молча сломаешь расширение, которое ищет его по строке.
> Имя эффекта = имя способности, это контракт данных ↔ кода.

### 15.5 Аура + урон по началу хода (Spirit Guardians — самый насыщенный предмет)

```
EFFECT: transfer:false, origin=Item.LTQm45DD4V2IqDpi
  flags.dae          = {stackable:"none", specialDuration:[], macroRepeat:"none"}
  flags.ActiveAuras  = {isAura:true, aura:"Enemy", radius:15, ignoreSelf:true}
  flags["dnd5e-helpers"] = {"rest-effect": "Ignore"}
  changes:
    system.attributes.movement.all  mode 0  "/2"
    flags.midi-qol.OverTime         mode 5  "turn=start, label=Spirit Guardians, damageRoll=(@spellLevel)d8,
                                             damageType=radiant, saveRemove=false, saveDC=@attributes.spelldc"
    macro.itemMacro                 mode 0  "@token @spellLevel @attributes.spelldc"
```

- `transfer:false` обязателен для ауры: DAE/Active Auras сам разносит эффект по попавшим в радиус,
  а не «навечно прикреплённым» к носителю.
- `damageRoll=(@spellLevel)d8` — формула считается Midi-QOL с подстановкой уровня; `saveRemove=false`
  = урон каждый ход, даже когда спасбросок пройден.
- Аура-макрос получает `args[0] === "on"`, `args[1]` = tokenId источника и сверяет ход:
  `lastArg.tokenId === game.combat?.current.tokenId`, затем `await fromUuid(lastArg.origin)` и
  **пересобирает предмет как `type:"weapon"`** (`mergeObject(duplicate(sourceItem), {type:"weapon", effects:[], flags:…})`),
  чтобы урон прошёл полным циклом Midi-QOL (критик, сопротивление, сообщение в чате).

### 15.6 Шаблон области → постоянный тайл на сцене (ловушки)

Калтропы / Капкан / Металлические шарики — `consumable`, и после использования «разбросанное»
должно остаться видимым на сцене. Решение: `[postActiveEffects]ItemMacro`, который берёт геометрию
размещённого шаблона и создаёт Tile:

```javascript
const workflow = args?.[0];
if (!workflow) return console.error("[TileMacro] Нет workflow (макрос не вызван Midi-QOL)");
const templateId = workflow.templateId, templateUuid = workflow.templateUuid;
if (!templateId || !templateUuid) return console.error("[TileMacro] Нет templateId/templateUuid");
// …по координатам MeasuredTemplate создаётся Tile с тектурой ловушки
```

Сопутствующие поля данных (все три предмета одинаково): `type.value:"trinket"`,
`actionType:"util"`|`"save"`, `target {value:"5"|"10", units:"ft", type:"square"}`,
`save {ability:"dex", dc:15|13|10, scaling:"flat"}` (плоский СЛ, не от заклинания),
`uses {value:1, max:"1", per:"charges", autoDestroy:true}`, `flags.midi-qol {AoETargetType:"any",
AoETargetTypeIncludeSelf:true, autoTarget:"default"}`; у Капкана дополнительно `activation.cost:0`,
`effectActivation:false` и `midiProperties.otherCondition`.

### 15.7 Чистые «носители действия» (ни школы, ни описания, ни эффекта)

«Взаимодействие с НПС», «Рывок(дополнительное перемещение)», «Уклонение» (версия-spell):
`type:"spell"`, `level 0`, `school ""`, `description ""`, эффектов нет — смысл только в кнопке листа.
У первой там же висит макрос-валидатор, который сам меряет дистанцию:

```javascript
const actorToken = canvas.tokens.controlled[0];
const target = Array.from(game.user.targets)[0];
const distance = canvas.grid.measureDistance(actorToken.center, target.center);
if (distance > 5) { /* ui.notifications.warn(...) и выход */ }
```

Дёшево даёт НПС/игроку «действие из PHB» без строчки в `registry.js`. Минус: в лог-файле и в чате
по такому предмету ничего не найдёшь — всегда пиши `description`.

### 15.8 Откуда предмет и что от него зависит (provenance)

- `flags.core.sourceId` — путь источника клона: `Compendium.<pack>.Item.<id>`, `Actor.<…>.Item.<…>` или
  **глубокий** `Scene.ocnaVUdPmSkjKizF.Token.ikyUSip7dK688Hqu.Actor.0aS8Zt5RihliUgVw.Item.3AGLfgGhEVyyBrS5`
  («Рога») — после дублирования/удаления сцены ссылка протухает (§12, поз.2).
- `flags.dnd5e.sourceId` + `flags.dnd5e.advancementOrigin` (вид `"<classItem>.<advancement>"`) — цепочка
  «класс → взятая черта»; при обновлении класса DAE/5e может перезаписать предмет.
- `flags.dnd5e.dependents` — обратные ссылки: у «Сон» там два
  `Scene.<id>.Token.<id>.Actor.<id>.ActiveEffect.<id>`. То есть созданные из предмета эффекты привязаны
  к **конкретной сцене**; пересоздание сцены оставляет мусорные dependents.
- Служебное, не трогать: `flags.srd5e {source, hash}`, `flags.babele`, `flags.cf` (compendium-folders),
  `flags["scene-packer"].hash`, `flags["item-piles"]`, `flags.gm-notes`, `flags.autoanimations`,
  `flags["chris-premades"]`, `flags.magicitems`.
- Частоты namespaces на 27 предметах: `midi-qol` 27, `midiProperties` 27, `tidy5e-sheet` 27, `core` 23,
  `dae` 15, `betterRolls5e` 13, `itemacro` 12, `dnd5e` 11, `srd5e` 8, `babele` 8, `cf` 5,
  `custom-character-sheet-sections` 4, `rest-recovery` 4, `chris-premades` 4, `beavers-crafting` 3,
  `item-piles` 2. Присутствие namespace ≈ «модуль когда-то был включён и дописал данные».
- Оформление в листе: `flags["custom-character-sheet-sections"].sectionName:"Generic Actions"` и
  `flags["rest-recovery"].data.recovery.enabled:false` — типовые для «действий», а не заклинаний.
- В описаниях работают inline-ссылки и команды чата: `@UUID[Item.x8vpwnIhQpvPDs52]{ягод}`,
  `@UUID[Compendium.laaru-dnd5-hw.spells.Item.7hdFEKqTGtjfTdwn]`, `[[/r 5d8]]`,
  `&amp;reference[prone]{распластаться}`. Макрос может читать свой `description` как данные.

### 15.9 Что заполнять по типам (инвентарь заполненности из 27 предметов)

| Тип | Всегда заполнено | Из практики обязательно |
|---|---|---|
| spell (12) | `preparation.mode`, `save.scaling`, `target.prompt`, `uses.prompt` | `activation.{type,cost}`, `actionType` (`util`/`save`/`summ`), `range.{value,units}`, `target.{value,type}`, `duration.{value,units}`, `materials.value`, `properties[]` (`vocal/somatic/material/concentration/ritual`), `level`, `school`, `ability` |
| feat (9) | только `save.scaling`, `target.prompt`, `uses.prompt` (остальное у большинства пустое) | `activation.type` (`action`/`bonus`/`special`/`react`), `actionType` (`other`/`util`), `type.value` (`race`/`monster`/`feat`), `uses.{value,max,per:"sr"|"charges"}`, `requirements`, `source.custom` |
| consumable (5) | `actionType`, `activation.type`, `type.value`, `uses.*`, `save.scaling`, `price`, `weight`, `rarity`, `identified` | `type.value` (`food`/`trinket`), `actionType` (`heal`/`util`/`save`), `uses {per:"charges", autoDestroy:true}`, `save {ability, dc, scaling:"flat"}`, `target.{value,units,type}` |
| weapon (1) | всё заполнено | `type {value:"natural"}`, `actionType:"mwak"`, `ability:"str"`, `damage.parts [["2d8 + @mod","piercing"]]`, `range {value:5, units:"ft"}`, `equipped:true` |

Дробные `weight.value: 0.002` и `price.value: 0.01` — норма. `damage.parts [["0", ""]]` (пустой урон-
заглушка у Сна и Факела) — способ заставить Midi-QOL показать карточку урона без урона.
`actionType:"summ"` + `preparation {mode:"always"}` + `materials {consumed:true, supply:10}` — «Вкусные
ягоды»: заклинание всегда подготовлено и создаёт 10 единиц материала.

### 15.10 Куда класть логику: в данные или в biyk_ext

| Логика | Куда | Почему |
|---|---|---|
| Числовой модификатор / преимущество / кубик бонуса | данные: ActiveEffect change (§15.2) | 0 строк кода, видно на листе и в DAE |
| «В начале хода — урон и спасбросок» | данные: `flags.midi-qol.OverTime` | Midi-QOL уже всё считает |
| Разовое действие по использованию предмета | данные: `onUseMacroName` + Item Macro | не надо плодить расширения |
| Статус-состояние (unconscious, prone) | данные: `flags.dnd5e.condition` | снимается вместе с эффектом |
| «Нельзя атаковать с преимуществом, если на цели есть эффект X» | biyk_ext: `midi-qol.preAttackRoll` (`avoid`) | мутирует чужой workflow — в данных не выразить |
| Отмена урона, диалог выбора, цепочки между актёрами, UI | biyk_ext (§3.4–§4.6) | нужен асинхронный контроль и DOM |
| Включить `disabled:true`-эффект при использовании | biyk_ext: `activate_effect` (уже готов) | данные сами себя не включат |
| Глобальные правила на сцену/погоду/бой | biyk_ext (§5–§9) | это вообще не про предметы |

Реальные пары «данные ↔ расширение» в этом мире:

| Предмет | Что в данных | Что в коде |
|---|---|---|
| Уклонение | `advantage.ability.check.dex`, `specialDuration ["turnStart"]` | `avoid` (`preAttackRoll`) — ищет эффект по имени |
| Отступление | эффект-носитель `disabled:true`, `["turnEnd","turnEndSource"]` | `attack-of-opportunity` — пропускает AoO по имени эффекта |
| Решительность * | `flags.midi-qol.advantage.all=1`, `uses {1, sr}` | `activate_effect` / общий `dnd5e.useItem` |
| Защита от зла и от добра | эффект-заглушка `transfer:true`, **без changes** | `protection_from_evil` (`name.includes("защита от зла и добра")`) |
| Убежище | `[isAttacked]ItemMacro` (DC 12 хардкод) | `sanctuary` — дублирует то же самое (см. грабли) |

> **Грабли, которые дало только это исследование.**
> 1. У «Убежище» спасбросок атакующего реализован **и** в Item Macro, **и** в расширении `sanctuary`
>    (оба делают проверку и пишут в чат). Один триггер — две реализации → двойной бросок/двойное
>    сообщение. Перед правкой способности ищи её имя **в обоих местах** (`flags.dae.macro` в предмете и
>    `Select-String -Path extensions/*/index.js -Pattern '<имя>'`).
> 2. Дубли одних и тех же способностей в разных подпапках (два «Отступление», «Уклонение» как feat и как
>    spell) синхронизируются вручную — правь сразу все копии.
> 3. Хардкод в макросах хуже хардкода в `index.js`: он не виден в `git diff` модуля. DC (`const DC = 12;`,
>    `const dc = 14;`), `ITEM_IDS`, `itemIdToAdd` — всё это лежит в данных мира.

### 15.11 Как снять такие данные самому

```powershell
cd Data/modules/biyk_ext/temp
python probe5.py      # поддерево от ROOT → dump/prog_items_full.json (+ foldersRaw.json, subtreeIds.json)
python analyze.py     # → dump/analysis.txt: поля по типам, эффекты, флаги, inventory change.key
```

- `temp/cdp.py` — мост: `CDP().eval_json("<JS во вкладке Foundry>")`. Мишень ищется по подстроке
  `localhost:30000` среди `http://localhost:9222/json`, websocket открывается с `suppress_origin=True`
  (без этого Chrome отвечает 403 на Handshake).
- Читай `pack.getIndex()` **до** обращения к `pack.folders` — индекс компендиума грузится лениво, иначе
  `folders` всегда пустой.
- Не вызывай `game.folders.contents.map(f => f.contents)`: геттер `Folder#contents` падает
  (`Cannot read properties of undefined (reading 'filter')`) на папках типов без загруженной коллекции.
  Во всех `probe*.py` есть обёртка `safe(label, fn)` — try/catch на каждую секцию дампа.
- Полный предмет: `i.toObject({dropExtraData: false})` + `(i.effects?.contents ?? []).map(e => e.toObject())`.
- Результат с кириллицей пиши **в файл UTF-8** и читай файлом: консоль PowerShell портит кодировку,
  а `$env:PYTHONIOENCODING=…` в этой оболочке не парсится.
- Меня `ROOT` в `probe5.py` на id любой другой папки (`dump/foldersRaw.json` — полная таблица parent'ов
  всех 33 Item-папок мира) — и получаешь такой же разбор для любого набора способностей.
