import {log} from "../utils/logger.js";
import {similarity} from "../utils/help.js"

export async function use(token, conf) {
    // Ищем предмет по имени (conf.item) или ID (conf.itemId)
    let item = null;
    await token.actor?.appliedEffects;
    await game.actors.get(token.actor.id);
    if (conf.itemId) {
        // Поиск по ID
        for (let _item of token.actor.items) {
            let my_similarity = similarity(_item.id,conf.itemId);

            if (my_similarity > 0.87){
                item = _item;
            }
        }
    } else if (conf.item) {
        // Поиск по имени (точное совпадение или содержит)
        item = token.actor.items.find(i =>
            i.id === conf.item ||
            i.name === conf.item ||
            i.name.toLowerCase().includes(conf.item.toLowerCase())
        );
    }

    if (!item) {
        console.error(token.actor.items, item)
        throw new Error(`Предмет "${conf.item || conf.itemId}" не найден`);
        return false;
    }

    // Используем предмет
    try {
        await item.use();
        log.info(`использую предмет ${conf.item || conf.itemId}`);
        return true;
    } catch (err) {
        log.error("ошибка при использовании:", err);
        ui.notifications.error("Не удалось использовать предмет");
        return false;
    }
}