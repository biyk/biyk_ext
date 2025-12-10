/**
 * Функция для отображения диалога и обработки выбора ячеек "Магического восстановления"
 * @param {Actor5e} actor - Актер, использующий способность.
 * @param {Item5e} abilityItem - Предмет способности "Магическое восстановление".
 */
async function _showArcaneRecoveryDialog(actor, abilityItem) {
    // 1. Определяем уровень волшебника и максимальный восстанавливаемый круг
    const wizardClass = actor.items.find(i => i.type === "class" && i.name.toLowerCase().includes("волшебник"));
    
    // Если класс "Волшебник" не найден, выходим
    if (!wizardClass) {
        return ui.notifications.warn(`${actor.name} не имеет класса Волшебник для использования этой способности.`);
    }

    const wizardLevel = wizardClass.system.levels;
    // Максимальный суммарный круг: половина уровня, округленная вверх
    const maxRecoveryLevel = Math.ceil(wizardLevel / 2);

    // 2. Получаем текущие данные о ячейках заклинаний
    const spellSlots = actor.system.spells;
    const availableSlots = [];
    
    // Перебираем ячейки с 1-го по 5-й круг (6-й и выше запрещены)
    for (let i = 1; i <= 5; i++) {
        const slotKey = `spell${i}`; // Например, 'spell1', 'spell2', ...
        const slotsUsed = spellSlots[slotKey]?.value || 0;
        const slotsTotal = spellSlots[slotKey]?.max || 0;
        
        // Добавляем только те ячейки, которые были использованы (value < max)
        if (slotsUsed < slotsTotal) {
            availableSlots.push({
                level: i,
                key: slotKey,
                used: slotsTotal - slotsUsed, // Сколько можно восстановить
                total: slotsTotal
            });
        }
    }

    if (availableSlots.length === 0) {
        return ui.notifications.info(`${actor.name} не имеет использованных ячеек заклинаний (1-5 кругов).`);
    }

    // 3. Создаем HTML-контент для диалога
    let slotOptionsHtml = `<p>Уровень Волшебника: <b>${wizardLevel}</b>.</p>`;
    slotOptionsHtml += `<p>Максимальный суммарный круг для восстановления: <b>${maxRecoveryLevel}</b>.</p>`;
    slotOptionsHtml += `<hr/>`;

    slotOptionsHtml += `<div id="arcane-recovery-slots">`;
    slotOptionsHtml += `<h3>Выберите ячейки для восстановления (макс. ${maxRecoveryLevel} суммарного круга):</h3>`;
    
    availableSlots.forEach(slot => {
        const maxRecoverable = slot.used;
        
        slotOptionsHtml += `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <label for="slot-level-${slot.level}">
                    Ячейка ${slot.level}-го круга (${slot.total} всего, ${slot.used} использовано):
                </label>
                <input 
                    type="number" 
                    id="slot-level-${slot.level}" 
                    data-level="${slot.level}"
                    data-key="${slot.key}"
                    value="0" 
                    min="0" 
                    max="${maxRecoverable}" 
                    style="width: 50px; text-align: center; margin-left: 10px;"
                />
            </div>
        `;
    });
    slotOptionsHtml += `</div>`;
    
    // Элемент для вывода текущей суммы выбранных кругов
    slotOptionsHtml += `<hr/><b><p id="recovery-sum-output">Выбрано суммарно: 0 (из ${maxRecoveryLevel})</p></b>`;


    // 4. Показываем диалог
    new Dialog({
        title: `${abilityItem.name}: Выбор ячеек`,
        content: slotOptionsHtml,
        buttons: {
            recover: {
                icon: '<i class="fas fa-magic"></i>',
                label: "Восстановить",
                callback: (html) => {
                    _handleArcaneRecovery(html, actor, maxRecoveryLevel, abilityItem);
                }
            },
            cancel: {
                icon: '<i class="fas fa-times"></i>',
                label: "Отмена",
                callback: () => console.log("Магическое восстановление отменено")
            }
        },
        default: "cancel",
        // Добавляем слушателя событий для обновления суммы выбранных кругов
        render: (html) => {
            const inputs = html.find('#arcane-recovery-slots input[type="number"]');
            
            // Функция для расчета и отображения текущей суммы
            const updateSum = () => {
                let currentSum = 0;
                inputs.each((i, input) => {
                    const level = parseInt($(input).data('level'));
                    const count = parseInt($(input).val());
                    currentSum += level * count;
                });
                
                const output = html.find('#recovery-sum-output');
                output.html(`Выбрано суммарно: <b>${currentSum}</b> (из ${maxRecoveryLevel})`);

                // Если сумма превышает лимит, подсвечиваем предупреждение
                if (currentSum > maxRecoveryLevel) {
                    output.css('color', 'red');
                } else {
                    output.css('color', 'inherit');
                }
            };

            // Привязываем событие изменения к каждому полю ввода
            inputs.on('change keyup', updateSum);
            // Запускаем один раз при открытии диалога
            updateSum();
        },
        close: () => console.log("Магическое восстановление закрыто")
    }).render(true);
}

/**
 * Обработка результата диалога и обновление ячеек актера
 */
async function _handleArcaneRecovery(html, actor, maxRecoveryLevel, abilityItem) {
    const inputs = html.find('#arcane-recovery-slots input[type="number"]');
    const updates = {}; // Объект для обновления ячеек актера
    let currentSum = 0;

    // 1. Собираем выбор и проверяем суммарный лимит
    inputs.each((i, input) => {
        const level = parseInt($(input).data('level'));
        const key = $(input).data('key');
        const count = parseInt($(input).val());
        
        currentSum += level * count;

        // Если выбрано количество > 0, подготавливаем обновление
        if (count > 0) {
            // spellSlots[key].value это ИСПОЛЬЗОВАННЫЕ ячейки
            // Уменьшение value означает ВОССТАНОВЛЕНИЕ ячеек
            // Если actor.system.spells.spell1.value = 2 (использовано), 
            // и мы восстанавливаем 1, новое значение должно стать 1
            const currentUsed = actor.system.spells[key].value;
            const newUsed = Math.max(0, currentUsed - count);
            
            updates[`system.spells.${key}.value`] = newUsed;
        }
    });

    // 2. Финальная проверка лимита
    if (currentSum > maxRecoveryLevel) {
        ui.notifications.error(`Ошибка: Суммарный круг выбранных ячеек (${currentSum}) превышает лимит (${maxRecoveryLevel}).`);
        // Возвращаем использование способности актеру, так как она не была применена
        // (Это потребует настройки ресурса способности, если она расходуется!)
        return false; 
    }

    // 3. Выполняем обновление актера (восстанавливаем ячейки)
    if (Object.keys(updates).length > 0) {
        await actor.update(updates);
        
        // 4. Отправляем сообщение в чат
        ChatMessage.create({
            speaker: ChatMessage.getSpeaker({actor}),
            content: `
                <div class="dnd5e chat-card">
                    <header class="card-header flexrow">
                        <img src="${abilityItem.img}" title="${abilityItem.name}" width="36" height="36"/>
                        <h3 class="item-name">${abilityItem.name}</h3>
                    </header>
                    <div class="card-content">
                        <b>${actor.name}</b> восстанавливает ячейки заклинаний.
                        Суммарный восстановленный круг: <b>${currentSum}</b>.
                    </div>
                </div>
            `
        });
        ui.notifications.info(`Ячейки для ${actor.name} успешно восстановлены (Суммарный круг: ${currentSum}).`);
    } else {
        ui.notifications.warn(`Не выбраны ячейки для восстановления.`);
    }
}


export function init() {
    // Регистрируем хук, который срабатывает после успешного использования предмета
    Hooks.on("dnd5e.useItem", (item, config, result) => {
        // Проверяем, что способность называется "Магическое восстановление" 
        // и что она была успешно использована (result.has.roll обычно означает успех).
        if (item.name === "Магическое восстановление" && item.actor && result) {
            // Запускаем диалог
            _showArcaneRecoveryDialog(item.actor, item);
        } else {
            console.log(item)
        }
    });

    if (game.user.isGM) {
        ui.notifications.info("Хук на 'Магическое восстановление' активирован.");
    }
}