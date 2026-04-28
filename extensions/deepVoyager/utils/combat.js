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
 * @param {Token} currentToken - текущий токен
 * @returns {Array} массив данных о токенах
 */
export function getVisibleCombatTokens(currentToken) {
    const visibleTokens = [];

    if (!game.combat?.combatants) return visibleTokens;

    for (const combatant of game.combat.combatants) {
        if (combatant.tokenId === currentToken.id) continue;

        const token = canvas.tokens.get(combatant.tokenId);
        if (!token) continue;

        const actorData = token.actor;
        if (!actorData) continue;

        // Проверка видимости (line of sight)
        let hasLineOfSight = false;
        try {
            const sightBackend = CONFIG.Canvas.polygonBackends?.sight;
            if (sightBackend && typeof sightBackend.testCollision === "function") {
                hasLineOfSight = !sightBackend.testCollision({
                    type: "sight",
                    source: currentToken.center,
                    destination: token.center,
                    mode: "any"
                });
            } else {
                const ray = new Ray(currentToken.center, token.center);
                hasLineOfSight = !canvas.walls.checkCollision(ray, { type: "sight", mode: "any" });
            }
        } catch(e) {
            hasLineOfSight = true;
        }

        if (!hasLineOfSight) continue;

        // Оружие в руках
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