export function init() {
// Регистрируем асинхронный хук, который срабатывает после обновления данных актера
Hooks.on("updateActor", async (actor, updateData, options, userId) => {
    
    // 1. Проверяем, что обновление касается HP и что оно сделано текущим пользователем
    // (Или ГМом, чтобы избежать дублирования диалога)
    // ВАЖНО: Мы убрали проверку userId, чтобы хук срабатывал независимо от того, кто меняет HP,
    // но чтобы диалог показывался владельцу актера или ГМу. 
    // В Foundry VTT, actor.update() (шаг 6) вызывает хук "updateActor" снова. 
    // Чтобы избежать бесконечного цикла, нужно убедиться, что мы не обрабатываем 
    // обновление, которое мы сами только что инициировали.
    
    // Проверка на обновление HP (убеждаемся, что значение HP действительно изменилось)
    const newHP = actor.system.attributes.hp.value;
    const oldHP = updateData?.system?.attributes?.hp?.value;

    // Если HP не менялось в этом обновлении, выходим (хотя вряд ли оно дойдет досюда, но на всякий случай)
    if (oldHP === undefined) return;
    
    // 2. Проверяем наличие способности "Неутомимая выносливость"
    const abilityName = "Неутомимая выносливость";
    const abilityItem = actor.items.find(i => i.name === abilityName);

    // Если у актера нет этой способности, выходим
    if (!abilityItem) return console.log('! Неутомимая выносливость');

    // 3. Проверяем, что HP упало до критического уровня (ниже 1)
    const currentHP = newHP; // currentHP уже содержит новое значение
    
    // Если HP 1 или выше, способность не нужна
    if (currentHP >= 1) return console.log('> 0');

    // 4. Проверяем, что способность доступна (имеет хотя бы 1 использование)
    // Проверка ресурса
    const usesRemaining = abilityItem.system.uses?.value;
    
    // Если usesRemaining не определено или < 1, то ресурса нет. Выходим.
    if (usesRemaining === undefined || usesRemaining < 1) return console.log('! Нет ресурса');

    // 5. Показываем диалог
    // Проверяем, кто должен видеть диалог: владелец актера или ГМ
    const isOwner = actor.isOwner;
    const isGM = game.user.isGM;

    // Если это не владелец актера и не ГМ, то не показываем диалог (можно скорректировать)
    if (!isOwner && !isGM) return console.log('! Не владелец и не ГМ');

    // --- Условия выполнены: HP < 1, способность есть, и есть ресурс ---

    const useReaction = await Dialog.confirm({
        title: abilityName,
        content: `
            <h2>Требуется реакция!</h2>
            <p style="font-size: 1.1em;">
                <b>${actor.name}</b>, ваше здоровье упало до <b>${currentHP}</b>.
                Вы хотите использовать <b>${abilityName}</b>, чтобы остаться на 1 HP?
                (Использований осталось: ${usesRemaining})
            </p>
        `,
        defaultYes: false // По умолчанию "Нет" для безопасности
    });

    // 6. Обрабатываем результат диалога
    if (useReaction) {
        // Устанавливаем HP равным 1
        // ВАЖНО: Передаем options, чтобы не вызывать хук updateActor снова (опционально, но рекомендуется)
        await actor.update({'system.attributes.hp.value': 1}, {relentless: true});
        
        // 7. Списываем одно использование
        // Предполагаем, что способность использует счетчик uses.value
        const newUses = Math.max(0, usesRemaining - 1); // Убеждаемся, что не уйдем в минус
        await abilityItem.update({'system.uses.value': newUses});

        // 8. Отправляем сообщение в чат о срабатывании
        ChatMessage.create({
            user: game.user.id,
            speaker: ChatMessage.getSpeaker({actor}),
            content: `
                <div class="dnd5e chat-card">
                    <header class="card-header flexrow">
                        <img src="${abilityItem.img}" title="${abilityName}" width="36" height="36"/>
                        <h3 class="item-name">${abilityName}</h3>
                    </header>
                    <div class="card-content">
                        <b>${actor.name}</b> использовал ${abilityName} и остается на <b>1 HP</b>!
                        (Использований осталось: ${newUses})
                    </div>
                </div>
            `
        });
    }
});

// Сообщение при загрузке, что хук активен
if (game.user.isGM) {
    ui.notifications.info("Хук на 'Неутомимую выносливость' активирован.");
}


}