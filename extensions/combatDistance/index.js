export function init() {
    const getSpeed = actor => actor?.system?.attributes?.movement?.walk || 0;

    // === Проверка, является ли пользователь DM ===
    const isDM = () => game.user.isGM;

    // === Хуки ===
    Hooks.on("combatTurn", async (combat, combatant) => {
        if (!isDM()) return;

        // Берем активного токена текущего комбатанта
        const tokenDoc = combatant.token;
        if (!tokenDoc) return;

        const baseSpeed = getSpeed(tokenDoc.actor);

        // Устанавливаем новый запас движения
        await tokenDoc.setFlag("world", "normalRemaining", baseSpeed);
        await tokenDoc.setFlag("world", "dashBonus", baseSpeed);

        ChatMessage.create({
            content: `<b>${tokenDoc.name}</b> начинает ход. Скорость: <b>${baseSpeed} фт.</b> (Рывок даёт +${baseSpeed} фт.)`,
            whisper: [game.user.id]
        });
    });

    Hooks.on("preUpdateToken", async (tokenDoc, change, options, userId) => {
        if (!isDM()) return;
        if (!game.combat || !game.combat.isActive) return;

        // Проверяем, было ли движение
        if (!("x" in change) && !("y" in change)) return;

        // Текущие координаты (до перемещения)
        const prevPos = { x: tokenDoc.x, y: tokenDoc.y };
        // Новые координаты
        const nextPos = {
            x: change.x ?? tokenDoc.x,
            y: change.y ?? tokenDoc.y
        };

        // --- Использование алгоритма Ray для подсчета клеток ---
        // Создаем луч от старой позиции к новой
        const ray = new Ray(prevPos, nextPos);

        // Измеряем дистанцию с учетом сетки сцены (gridSpaces: true)
        // [0] берем первый элемент, так как measureDistances возвращает массив
        const movedDist = canvas.grid.measureDistances([{ ray }], { gridSpaces: true })[0];

        if (movedDist === 0) return;

        // Получаем текущие запасы из флагов
        let normalRemaining = tokenDoc.getFlag("world", "normalRemaining") ?? getSpeed(tokenDoc.actor);
        let dashBonus = tokenDoc.getFlag("world", "dashBonus") ?? getSpeed(tokenDoc.actor);

        let leftToSpend = movedDist;

        // 1. Тратим обычное движение
        const takeFromNormal = Math.min(normalRemaining, leftToSpend);
        normalRemaining -= takeFromNormal;
        leftToSpend -= takeFromNormal;

        // 2. Тратим бонус рывка
        if (leftToSpend > 0) {
            const takeFromDash = Math.min(dashBonus, leftToSpend);
            dashBonus -= takeFromDash;
            leftToSpend -= takeFromDash;
        }

        // Сохраняем обновленные значения
        await tokenDoc.setFlag("world", "normalRemaining", Math.max(normalRemaining, 0));
        await tokenDoc.setFlag("world", "dashBonus", Math.max(dashBonus, 0));

        // Сообщение в чат
        ChatMessage.create({
            content: `👣 <b>${tokenDoc.name}</b>: пройдено ${movedDist} фт.<br>
                      Осталось: <b>${normalRemaining.toFixed(0)}</b> фт.<br>
                      Рывок: <b>${dashBonus.toFixed(0)}</b> фт.`,
            whisper: [game.user.id]
        });

        if (normalRemaining <= 0 && dashBonus <= 0) {
            ui.notifications.warn(`${tokenDoc.name} исчерпал запас движения!`);
        }
    });

    // Очистка при завершении боя или смене раунда
    Hooks.on("preUpdateCombat", async (combat, change) => {
        if (!isDM()) return;
        // Если меняется раунд или бой заканчивается
        if (change.round || change.active === false) {
            for (let combatant of combat.combatants) {
                const tokenDoc = combatant.token;
                if (tokenDoc) {
                    await tokenDoc.unsetFlag("world", "normalRemaining");
                    await tokenDoc.unsetFlag("world", "dashBonus");
                }
            }
        }
    });
}