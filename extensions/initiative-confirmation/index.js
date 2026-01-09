// Хук срабатывающий ДО броска инициативы
Hooks.on('createCombat', async () => {
    // Получаем текущего активного игрока
    let player = game.user;

    // Проверяем, существует ли активный персонаж игрока
    let actor = player.character || player;
    if (!actor) return;

    console.log(game.user);
    // Ищем способность "Inspiring Presence"
    let inspiringPresenceAbility = actor.items.find(item => item.name === "Вдохновляющее присутствие");

    // Проверяем наличие нужной способности
    if (inspiringPresenceAbility && inspiringPresenceAbility.isEmbedded) {
        // Показываем диалоговое окно
        const confirmResult = await Dialog.confirm({
            title: 'Использовать Вдохновляющее присутствие?',
            content: `<p>Хотите активировать эффект "Вдохновляющее присутствие"? Это увеличит здоровье союзников.</p>`,
        });


        // Активируем способность при положительном ответе
        if (confirmResult) {
            useInspiringPresence(actor, inspiringPresenceAbility);
        }
    } else {
        ui.notifications.info(`Способность "Вдохновляющее присутствие" не найдена`);
        console.log(actor.items)
    }
});

// Функция активации эффекта вдохновляющего присутствия
async function useInspiringPresence(actor, inspiringPresenceAbility) {

    // Уменьшаем заряд или используем ресурс (если предусмотрено системой)
    inspiringPresenceAbility.use();
    ui.notifications.info(`Способность "Вдохновляющее присутствие" успешно применена.`);
}
