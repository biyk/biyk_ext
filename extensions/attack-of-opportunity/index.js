// ============================================
// Attack of Opportunity (Провокационная атака)
// ============================================
export function init() {
    const isDM = () => game.user.isGM;
    if (!isDM()) return;

    // Вспомогательная функция для безопасной установки цели и атаки
    async function setTargetAndAttack(attackerToken, targetToken, item) {
        const currentUser = game.user;
        await currentUser.updateTokenTargets([targetToken.id]);
        await new Promise(resolve => setTimeout(resolve, 50));
        await item.use({ target: [targetToken] });
    }

    function getMeleeWeapons(actor) {
        if (!actor?.items) return [];
        return actor.items.filter(item =>
            item.type === 'weapon' && item.system.actionType === 'mwak' // только ближнее
        );
    }

    function getRandomMeleeWeapon(actor) {
        const weapons = getMeleeWeapons(actor);
        if (weapons.length === 0) return null;
        return weapons[Math.floor(Math.random() * weapons.length)];
    }

    // Возвращает все клетки, которые занимает токен (по bounding box)
    function getOccupiedCells(tokenData) {
        const gs = canvas.grid.size;
        const colStart = Math.floor(tokenData.x / gs);
        const rowStart = Math.floor(tokenData.y / gs);
        const colEnd = Math.floor((tokenData.x + tokenData.w - 1) / gs);
        const rowEnd = Math.floor((tokenData.y + tokenData.h - 1) / gs);
        const cells = [];
        for (let r = rowStart; r <= rowEnd; r++) {
            for (let c = colStart; c <= colEnd; c++) {
                cells.push({ r, c });
            }
        }
        return cells;
    }

    // Минимальное расстояние между клетками двух токенов (Chebyshev, в клетках)
    function getCellDistance(tokenA, tokenB) {
        const cellsA = getOccupiedCells(tokenA);
        const cellsB = getOccupiedCells(tokenB);
        let min = Infinity;
        for (const a of cellsA) {
            for (const b of cellsB) {
                const dist = Math.max(Math.abs(a.r - b.r), Math.abs(a.c - b.c));
                if (dist < min) min = dist;
            }
        }
        return min;
    }

    // Проверка, находится ли цель в пределах досягаемости (reach в футах)
    function isWithinReach(attacker, target, reachFeet) {
        const reachCells = Math.max(1, Math.floor(reachFeet / 5)); // 5ft → 1 кл, 10ft → 2 кл
        const dist = getCellDistance(attacker, target);
        return dist <= reachCells;
    }

    Hooks.on("preUpdateToken", async (tokenDocument, updateData, options, userId) => {
        if (updateData.x === undefined && updateData.y === undefined) return;

        const movingToken = canvas.tokens.get(tokenDocument.id);
        if (!movingToken) return;

        // Проверка эффекта "Отступление" (Disengage) у двигающегося токена
        let hasDisengage = false;
        if (movingToken.actor) {
            hasDisengage = movingToken.actor.appliedEffects.some(e =>
                e.name.toLowerCase().includes("disengage") ||
                e.name.toLowerCase().includes("отступление")
            );
            console.log('[AoO] ', hasDisengage, movingToken.actor);
        }
        if (!hasDisengage && movingToken.actor?.flags?.["midi-qol"]?.disengage) {
            hasDisengage = true;
        }
        if (hasDisengage) {
            console.log(`[AoO] ${movingToken.name} имеет эффект Отступление, атаки по возможности не触发ются.`);
            return;
        }

        const startPoint = { x: tokenDocument.x, y: tokenDocument.y };
        const newX = updateData.x ?? startPoint.x;
        const newY = updateData.y ?? startPoint.y;
        const endPoint = { x: newX, y: newY };
        if (startPoint.x === endPoint.x && startPoint.y === endPoint.y) return;

        const movingDisposition = tokenDocument.disposition;

        for (let potentialAttacker of canvas.tokens.placeables) {
            if (potentialAttacker.id === movingToken.id) continue;
            const attackerDisposition = potentialAttacker.document.disposition;
            if (attackerDisposition === 1 || attackerDisposition === 0) {
                if (movingDisposition !== -1) continue;
            }
            if (!potentialAttacker.actor || potentialAttacker.actor.system.attributes.hp.value <= 0) continue;

            const isPlayer = potentialAttacker.actor.hasPlayerOwner;
            let weapon = null;
            if (!isPlayer) {
                weapon = getRandomMeleeWeapon(potentialAttacker.actor);
                if (!weapon) continue;
            }

            // Дальность атаки: у оружия system.range.value (5 или 10), по умолчанию 5
            const attackRange = weapon?.system.range?.value ?? 5;

            // Моки для проверки клеточной дистанции
            const startMock = { x: startPoint.x, y: startPoint.y, w: movingToken.w, h: movingToken.h };
            const endMock = { x: endPoint.x, y: endPoint.y, w: movingToken.w, h: movingToken.h };
            const wasInRange = isWithinReach(potentialAttacker, startMock, attackRange);
            const isInRange = isWithinReach(potentialAttacker, endMock, attackRange);

            // АоА только если покинул зону досягаемости полностью
            if (!(wasInRange && !isInRange)) continue;

            // ---- Проверка, доступна ли реакция у атакующего ----
            let canReact = true;
            const actorAttacker = potentialAttacker.actor;
            console.log(actorAttacker, ' атакует');
            if (game.modules.get("midi-qol")?.active && game.midiqol?.canUseReaction) {
                canReact = game.midiqol.canUseReaction(actorAttacker);
            } else if (actorAttacker.flags?.["midi-qol"]?.reactionUsed === true) {
                canReact = false;
            }
            if (!canReact) {
                console.log(`[AoO] У ${potentialAttacker.name} нет доступной реакции, пропускаем`);
                continue;
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

    console.log("[Attack of Opportunity] Модуль инициализирован (клеточная проверка досягаемости, учёт Отступления)");
}