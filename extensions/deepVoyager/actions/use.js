import {log} from "../utils/logger.js";
import {similarity} from "../utils/help.js"

/**
 * Использовать предмет от имени токена.
 *
 * Атака в dnd5e/midi-qol бьёт по game.user.targets — общему состоянию пользователя,
 * а не по «цели актёра». Поэтому цель передаём явно (targetId из плана хода) и в любом
 * случае выбрасываем из целей сам действующий токен: иначе оставшаяся с прошлого хода
 * цель (часто — этот же боец) превращает удар в удар по себе.
 */
export async function use(token, conf, targetId = null) {
    // Ищем предмет по имени (conf.item) или ID (conf.itemId)
    let item = null;
    await token.actor?.appliedEffects;
    await game.actors.get(token.actor.id);
    if (conf?.itemId) {
        // Поиск по ID
        for (let _item of token.actor.items) {
            let my_similarity = similarity(_item.id,conf.itemId);

            if (my_similarity > 0.87){
                item = _item;
            }
        }
    } else if (conf?.item) {
        // Поиск по имени (точное совпадение или содержит)
        item = token.actor.items.find(i =>
            i.id === conf.item ||
            i.name === conf.item ||
            i.name.toLowerCase().includes(conf.item.toLowerCase())
        );
    }

    if (!item) {
        console.error(token.actor.items, item)
        throw new Error(`Предмет "${conf?.item || conf?.itemId}" не найден`);
    }

    // --- Цель: явная из плана, без самого себя и союзников ---
    const planned = targetId ? canvas.tokens.get(targetId) : null;
    const stale = Array.from(game.user.targets);
    if (stale.some(t => t.id === token.id)) {
        log.warn(`${token.name}: в целях оказался сам актёр — исключаю`);
    }

    // При fallback на game.user.targets фильтруем союзников по disposition.
    const myDisp = token.document?.disposition ?? 0;
    const hostileStale = stale.filter(t => (t.document?.disposition ?? 0) !== myDisp);

    // Цель из плана — единственный источник истины: не подставляем вместо неё
    // «висящую» цель прошлого хода. Без цели в плане — только текущие цели, тоже без себя и союзников.
    const ids = targetId
        ? (planned && planned.id !== token.id ? [planned.id] : [])
        : hostileStale.map(t => t.id);
    game.user.updateTokenTargets(ids);

    // Атака без цели — это не «удар в пустоту», а удар по остаткам game.user.targets.
    const isAttack = ["mwak", "rwak"].includes(item.system?.actionType);
    if (isAttack && ids.length === 0) {
        log.warn(`${token.name}: «${item.name}» — атака без цели, действие пропущено`);
        return false;
    }

    // Используем предмет
    try {
        await item.use();
        log.info(`использую предмет ${conf?.item || conf?.itemId}`);
        return true;
    } catch (err) {
        log.error("ошибка при использовании:", err);
        ui.notifications.error("Не удалось использовать предмет");
        return false;
    }
}
