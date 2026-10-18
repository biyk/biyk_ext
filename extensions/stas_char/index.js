export function init() {
    Hooks.on("dnd5e.useItem", async (item) => {
        const PREFIX = '[SorceryFlex]';
        const actor = item.actor;   // берём актора прямо из предмета

        if (!actor || !item) {
            console.error(`${PREFIX} Нет актора/предмета`);
            return;
        }

        // Только для заклинаний
        if (item.type !== "spell" || item.system.preparation.mode==="pact") return;
        console.log(item, item.system.preparation.mode);
        // Уровень ячейки = уровень заклинания в клоне предмета (уже выбран в диалоге)
        const spellLevel = item.system.level;
        if (!spellLevel || spellLevel === 0) return;   // кантрипы не трогаем

        const COST_TABLE = { 1: 2, 2: 3, 3: 5, 4: 6, 5: 7 };
        const cost = COST_TABLE[spellLevel];
        if (!cost) {
            console.warn(`${PREFIX} Уровень ${spellLevel} не поддерживается`);
            return;
        }

        // Ищем ресурс "Очки чар"
        const resourceItem = actor.items.find(i => i.name === 'Очки чар');
        if (!resourceItem) {
            ui.notifications.warn('Ресурс "Очки чар" не найден в инвентаре.');
            return;
        }

        const uses = resourceItem.system.uses;
        if (!uses) {
            ui.notifications.warn('У предмета "Очки чар" нет счётчика использований.');
            return;
        }

        const currentPoints = uses.value ?? 0;
        console.log(`${PREFIX} Требуется ${cost} очков для ячейки ${spellLevel} уровня. Доступно: ${currentPoints}`);

        if (currentPoints < cost) {
            ui.notifications.warn(`Недостаточно очков чародейства (нужно ${cost}, есть ${currentPoints})`);
            return;   // не отменяем каст – просто предупреждаем, ячейка потратится обычным образом
        }

        // 1. Чтобы ячейка не потратилась, временно увеличиваем её количество
        const spellKey = `spell${spellLevel}`;
        const slots = actor.system.spells[spellKey];
        if (slots) {
            await actor.update({ [`system.spells.${spellKey}.value`]: slots.value + 1 });
            // Когда заклинание использует ячейку, счётчик вернётся к исходному значению,
            // то есть ячейка фактически не израсходуется.
        }

        // 2. Тратим очки чар
        const newPoints = currentPoints - cost;
        await actor.items.get(resourceItem.id).update({ 'system.uses.value': newPoints });

        console.log(`${PREFIX} Списано ${cost} очков. Осталось: ${newPoints}. Ячейка не тратится (была предварительно восстановлена).`);
    });
}