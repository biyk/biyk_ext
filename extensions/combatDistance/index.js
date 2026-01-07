// === Movement Tracker — green decreases first, yellow = normalRemaining + dashBonus ===
// Foundry v11, D&D5e — ТОЛЬКО ДЛЯ DM
// Без визуальных кругов, только сообщения в чат

export function init() {

    let getSpeed = actor => actor?.system?.attributes?.movement?.walk || 0;

// === Проверка, является ли пользователь DM ===
    const isDM = () => {
        return game.user.isGM;
    };

// === Хуки ===
    Hooks.on("combatTurn", async (combat, combatant) => {
        if (!isDM()) return;

        let token = canvas.tokens.objects.children.filter(token=>token.id===game.combat.nextCombatant.tokenId)[0];

        if (!token) return;
        let baseSpeed = getSpeed(token.actor);

        // Устанавливаем новый запас движения для текущего хода
        await token.document.setFlag("world", "normalRemaining", baseSpeed);
        await token.document.setFlag("world", "dashBonus", baseSpeed);

        // Сообщение только для DM (whisper)
        ChatMessage.create({
            content: `<b>${token.name}</b> начинает ход. Скорость: <b>${baseSpeed} фт.</b> (Рывок даёт +${baseSpeed} фт.)`,
            whisper: [game.user.id],
            speaker: { alias: token.name }
        });
    });

    Hooks.on("updateToken", async (tokenDoc, change) => {
        if (!isDM()) return;

        if (!("x" in change) && !("y" in change)) return;
        const token = canvas.tokens.get(tokenDoc.id);
        if (!token) return;
        const actor = token.actor;
        if (!actor) return;

        const prevX = token.x;
        const prevY = token.y;
        const newX = change.x ?? prevX;
        const newY = change.y ?? prevY;
        const grid = canvas.scene.grid;
        const movedDist = Math.hypot(newX - prevX, newY - prevY) / grid.size * grid.distance;

        // Получаем текущие запасы
        let normalRemaining = tokenDoc.getFlag("world", "normalRemaining");
        let dashBonus = tokenDoc.getFlag("world", "dashBonus");
        const baseSpeed = getSpeed(actor);

        if (normalRemaining === undefined || normalRemaining === null) normalRemaining = baseSpeed;
        if (dashBonus === undefined || dashBonus === null) dashBonus = baseSpeed;

        let leftToSpend = movedDist;

        // Сначала забираем из обычного движения
        if (leftToSpend > 0) {
            const takeFromNormal = Math.min(normalRemaining, leftToSpend);
            normalRemaining -= takeFromNormal;
            leftToSpend -= takeFromNormal;
        }

        // Если ещё осталось — берём из бонуса рывка
        if (leftToSpend > 0) {
            const takeFromDash = Math.min(dashBonus, leftToSpend);
            dashBonus -= takeFromDash;
            leftToSpend -= takeFromDash;
        }

        // Защита от отрицательных значений
        normalRemaining = Math.max(normalRemaining, 0);
        dashBonus = Math.max(dashBonus, 0);

        await tokenDoc.setFlag("world", "normalRemaining", normalRemaining);
        await tokenDoc.setFlag("world", "dashBonus", dashBonus);

        // Сообщение только для DM (whisper)
        ChatMessage.create({
            content: `${actor.name} прошёл ${movedDist.toFixed(1)} фт. осталось: <b>${normalRemaining.toFixed(1)} фт.</b>, бонус рывка: <b>${dashBonus.toFixed(1)} фт.</b>`,
            whisper: [game.user.id],
            speaker: { alias: actor.name }
        });

        if (normalRemaining <= 0 && dashBonus <= 0) {
            ui.notifications.warn(`${actor.name} исчерпал весь запас движения (включая рывок).`);
        }
    });

    Hooks.on("preUpdateCombat", async (combat, combatant) => {
        if (!isDM()) return;
        // Очищаем флаги при смене раунда/хода
        for (let token of canvas.tokens.placeables){
            await token.document.unsetFlag("world", "normalRemaining");
            await token.document.unsetFlag("world", "dashBonus");
        }
    });
}
