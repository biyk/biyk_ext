/**
 * Получение информации о токенах из боя
 */

import { getStatus } from "./help.js";

/**
 * Получает информацию о текущем токене в бою
 * @param {Combat} combat - объект боя
 * @param {Combatant} combatant - текущий участник боя
 * @returns {Object} данные токена
 */
export function getCurrentTokenData(combat, combatant) {
    const token = canvas.tokens.get(combatant.tokenId);
    if (!token) return null;

    return {
        token: token,
        name: token.name,
        x: token.x,
        y: token.y,
        speed: token.actor?.system?.attributes?.movement?.walk || 0,
        step: canvas.grid.size,
        status: getStatus(token.actor),
        disposition: token.document?.disposition ?? 0,
        languages: [...(token.actor?.system?.traits?.languages?.value || [])].join(", ") || "common"
    };
}

/**
 * Получает информацию о всех видимых токенах боя (кроме текущего)
 * С учётом распространения информации между союзниками в радиусе 30 футов.
 * @param {Token} currentToken - текущий токен
 * @returns {Array} массив данных о токенах
 */
export function getVisibleCombatTokens(currentToken) {
    const visibleTokens = [];
    if (!game.combat?.combatants) return visibleTokens;

    // Текущий disposition и радиус обмена информацией (30 футов)
    const currentDisposition = currentToken.document?.disposition ?? 0;
    const shareRadiusFeet = 30;
    const shareRadiusPx = (shareRadiusFeet / 5) * canvas.grid.size;

    // Собираем всех союзных токенов на сцене (с тем же disposition)
    const allies = canvas.tokens.placeables.filter(t =>
        t.id !== currentToken.id &&
        (t.document?.disposition ?? 0) === currentDisposition
    );

    for (const combatant of game.combat.combatants) {
        if (combatant.tokenId === currentToken.id) continue;

        const token = canvas.tokens.get(combatant.tokenId);
        if (!token) continue;
        const actorData = token.actor;
        if (!actorData) continue;

        // 1. Прямая видимость от текущего токена
        let hasLineOfSight = false;
        try {
            const ray = new Ray(currentToken.center, token.center);
            const collision = canvas.walls.checkCollision(ray, { type: "sight", mode: "any" });
            hasLineOfSight = !collision;
        } catch(e) {
            console.error("[getVisibleCombatTokens] LOS direct check failed:", e);
            hasLineOfSight = false;
        }

        let isVisible = hasLineOfSight;
        if (!isVisible) {
            // 2. Проверка, есть ли союзник в радиусе 30 футов от currentToken,
            // который видит этого кандидата
            for (const ally of allies) {
                // Расстояние между союзником и текущим токеном
                const distToAlly = Math.hypot(ally.center.x - currentToken.center.x, ally.center.y - currentToken.center.y);
                if (distToAlly > shareRadiusPx) continue;

                // Проверка прямой видимости от союзника к кандидату
                let allySees = false;
                try {
                    const rayAlly = new Ray(ally.center, token.center);
                    const collisionAlly = canvas.walls.checkCollision(rayAlly, { type: "sight", mode: "any" });
                    allySees = !collisionAlly;
                } catch(e) {
                    allySees = false;
                }
                if (allySees) {
                    isVisible = true;
                    break;
                }
            }
        }

        if (!isVisible) continue;

        // Оружие в руках, AC, статус и пр.
        let equippedWeapon = null;
        const weapons = actorData.items.filter(i => (i.type === "weapon" || i.type === "equipment") && i.system.equipped);
        if (weapons.length) {
            equippedWeapon = { name: weapons.map(w => w.name).join(", "), id: weapons.map(w => w.id).join(", ") };
        }

        const ac = actorData.system.attributes.ac?.value || 10;
        const status = getStatus(actorData);

        visibleTokens.push({
            id: token.id,
            name: token.name,
            disposition: token.document?.disposition ?? 0,
            x: token.x,
            y: token.y,
            weapon: equippedWeapon,
            ac: ac,
            status: status
        });
    }

    return visibleTokens;
}

/**
 * Группирует токены по отношению к текущему
 * @param {Array} visibleTokens - видимые токены
 * @param {number} currentDisposition - disposition текущего токена
 * @returns {Object} { friends, enemies, neutrals }
 */
export function groupTokensByDisposition(visibleTokens, currentDisposition) {
    const friends = [];
    const enemies = [];
    const neutrals = [];

    for (const t of visibleTokens) {
        if (currentDisposition===-2){
            if (t.disposition === 0) {
                neutrals.push(t);
            } else if (t.disposition === -1) {
                friends.push(t);
            } else {
                enemies.push(t);
            }
        }else {
            if (t.disposition === 0) {
                neutrals.push(t);
            } else if (t.disposition === currentDisposition) {
                friends.push(t);
            } else {
                enemies.push(t);
            }
        }

    }

    return { friends, enemies, neutrals };
}