export function target(token, conf) {
    if (!conf?.id) {
        console.warn("target: ID цели не передан");
        return;
    }
    
    const targetToken = canvas.tokens.placeables.find(t => t.id === conf.id);
    if (!targetToken) {
        console.warn(`target: токен с ID ${conf.id} не найден`);
        return;
    }
    
    game.user.updateTokenTargets([conf.id]);
    console.log(`target: выбрана цель ${targetToken.name} (${conf.id})`);
}