import {log} from "../utils/logger.js";

export function target(token, conf) {
    if (!conf?.id) {
        log.warn("ID цели не передан");
        return;
    }
    
    const targetToken = canvas.tokens.placeables.find(t => t.id === conf.id);
    if (!targetToken) {
        log.warn(`токен с ID ${conf.id} не найден`);
        return;
    }
    
    game.user.updateTokenTargets([conf.id]);
    log.info(`выбрана цель ${targetToken.name} (${conf.id})`);
}