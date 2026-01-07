export function init() {
// Хук срабатывает при использовании любого предмета
Hooks.on("dnd5e.useItem", async (item, config, options) => {
    // Нам нужен актер, владеющий предметом
    const actor = item.actor;
    if (!actor) return;

    // Имя предмета, который использовали (например, "Решительность")
    const itemName = item.name;

    console.log(`[Auto-Effect] Использован предмет: ${itemName}. Ищу эффекты...`);

    // 1. Собираем ВСЕ эффекты (с актера и с его предметов)
    // Используем тот же надежный метод, что и раньше
    let allEffects = [
        ...actor.effects.contents,
        ...actor.items.reduce((acc, i) => acc.concat(i.effects.contents), [])
    ];

    // 2. Ищем подходящий эффект
    // Используем .includes, чтобы найти "Решительность *" по запросу "Решительность"
    // Или можно использовать .startsWith для точности
    let targetEffect = allEffects.find(e => e.name.includes(itemName));

    // Если эффект найден
    if (targetEffect) {
        console.log(targetEffect)
        // 3. Проверяем, выключен ли он (disabled: true)
        if (targetEffect.disabled) {
            // Включаем его
            //await targetEffect.update({disabled: false});
            
            // Сообщение для ГМа/Игрока
            ui.notifications.info(`Автоматически активирован эффект: "${targetEffect.name}"`);
            console.log(`[Auto-Effect] Активирован ${targetEffect.name}`);
        } else {
            console.log(`[Auto-Effect] Эффект ${targetEffect.name} уже активен, пропускаем.`);
        }
    } else {
        console.log(`[Auto-Effect] Эффект с именем, похожим на "${itemName}", не найден.`);
    }
});


}
