export async function use(token, conf) {
    // Ищем предмет по имени (conf.item) или ID (conf.itemId)
    let item = null;
    
    if (conf.itemId) {
        // Поиск по ID
        item = token.actor.items.get(conf.itemId);
    } else if (conf.item) {
        // Поиск по имени (точное совпадение или содержит)
        item = token.actor.items.find(i => 
            i.id === conf.item || 
            i.name === conf.item ||
            i.name.toLowerCase().includes(conf.item.toLowerCase())
        );
    }
    
    if (!item) {
        ui.notifications.warn(`Предмет "${conf.item || conf.itemId}" не найден`);
        return false;
    }

    // Используем предмет
    try {
        await item.use();
        console.log(`use: использую предмет ${conf.item || conf.itemId}`);
        return true;
    } catch (err) {
        console.error("use: ошибка при использовании:", err);
        ui.notifications.error("Не удалось использовать предмет");
        return false;
    }
}