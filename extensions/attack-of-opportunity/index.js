// ============================================
// Attack of Opportunity (Провокационная атака)
// ============================================
export function init() {
    // Вспомогательная функция для безопасной установки цели и атаки
    async function setTargetAndAttack(attackerToken, targetToken, item) {
        const currentUser = game.user;
        // Устанавливаем цель (токен, который убегает)
        await currentUser.updateTokenTargets([targetToken.id]);
        // Даём системе 50 мс на обработку
        await new Promise(resolve => setTimeout(resolve, 50));
        // Атакуем
        await item.use({ target: [targetToken] });
    }

    function getMeleeWeapons(actor) {
        if (!actor?.items) return [];
        return actor.items.filter(item =>
            item.type === 'weapon');
    }

    function getRandomMeleeWeapon(actor) {
        const weapons = getMeleeWeapons(actor);
        if (weapons.length === 0) return null;
        return weapons[Math.floor(Math.random() * weapons.length)];
    }

    Hooks.on("preUpdateToken", async (tokenDocument, updateData, options, userId) => {
        if (updateData.x === undefined && updateData.y === undefined) return;

        const movingToken = canvas.tokens.get(tokenDocument.id);
        if (!movingToken) return;

        const startPoint = { x: tokenDocument.x, y: tokenDocument.y };
        const newX = updateData.x ?? startPoint.x;
        const newY = updateData.y ?? startPoint.y;
        const endPoint = { x: newX, y: newY };
        if (startPoint.x === endPoint.x && startPoint.y === endPoint.y) return;

        const movingDisposition = tokenDocument.disposition;

        for (let potentialAttacker of canvas.tokens.placeables) {
            if (potentialAttacker.id === movingToken.id) continue;
            if (potentialAttacker.document.disposition !== -movingDisposition) continue;
            if (!potentialAttacker.actor || potentialAttacker.actor.system.attributes.hp.value <= 0) continue;

            //TODO potentialAttacker - attak range
            const isPlayer = potentialAttacker.actor.hasPlayerOwner;
            let weapon = null;
            if (!isPlayer) {
                weapon = getRandomMeleeWeapon(potentialAttacker.actor);
                if (!weapon) continue;
            }

            console.log(weapon);
            let attakRange = weapon?.system.range.value || 5;
            const wasInRange = canvas.grid.measureDistance(potentialAttacker, startPoint) <= attakRange;
            const isInRange = canvas.grid.measureDistance(potentialAttacker, endPoint) <= attakRange;
            if (!(wasInRange && !isInRange)) continue;

            // ---- Проверка, доступна ли реакция у атакующего ----
            let canReact = true;
            const actorAttacker = potentialAttacker.actor;

            console.log(actorAttacker ,' атакует');
            // 1. Проверка через Midi-QOL (если установлен)
            if (actorAttacker.flags?.["midi-qol"]?.actions.reaction === true) {
                canReact = false;
            }
            // 4. Если ничего не сработало, считаем что реакция доступна (можно всегда)
            if (!canReact) {
                console.log(`[AoO] У ${potentialAttacker.name} нет доступной реакции, пропускаем`);
                continue;   // переход к следующему потенциальному атакующему
            }



            if (!isPlayer) {
                // NPC: атакуем автоматически
                try {
                    await setTargetAndAttack(potentialAttacker, movingToken, weapon);
                    await ChatMessage.create({
                        content: `<strong>${potentialAttacker.name}</strong> совершает атаку по возможности против <strong>${movingToken.name}</strong>!`,
                        speaker: ChatMessage.getSpeaker({ token: potentialAttacker })
                    });
                } catch (err) {
                    console.error(`[AoO] Ошибка атаки NPC ${potentialAttacker.name}:`, err);
                }
                break;
            }
            else {
                const weapons = getMeleeWeapons(potentialAttacker.actor);
                if (weapons.length === 0) continue;

                const buttons = {};
                for (const w of weapons) {
                    buttons[w.id] = {
                        icon: '<i class="fas fa-fist-raised"></i>',
                        label: w.name,
                        callback: async () => {
                            try {
                                await setTargetAndAttack(potentialAttacker, movingToken, w);
                                await ChatMessage.create({
                                    content: `<strong>${potentialAttacker.name}</strong> использует реакцию и атакует <strong>${movingToken.name}</strong> оружием «${w.name}»!`,
                                    speaker: ChatMessage.getSpeaker({ token: potentialAttacker })
                                });
                            } catch (err) {
                                console.error(`[AoO] Ошибка атаки игрока ${potentialAttacker.name}:`, err);
                            }
                        }
                    };
                }
                buttons.cancel = {
                    icon: '<i class="fas fa-times"></i>',
                    label: "Отмена",
                    callback: () => console.log(`[AoO] ${potentialAttacker.name} отказался от атаки.`)
                };

                const dialog = new Dialog({
                    title: `⚔️ Атака по возможности: ${potentialAttacker.name}`,
                    content: `<p>${movingToken.name} выходит из зоны вашей досягаемости. У вас есть реакция, чтобы атаковать.</p><p><strong>Выберите оружие:</strong></p>`,
                    buttons: buttons,
                    default: "cancel"
                });
                dialog.render(true);
                setTimeout(() => {
                    if (dialog.rendered) dialog.close();
                }, 10000);
                break;
            }
        }
    });

    console.log("[Attack of Opportunity] Модуль инициализирован (с принудительной установкой цели)");
}