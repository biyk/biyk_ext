import {move} from "./actions/move.js";
import {target} from "./actions/target.js";
import {use} from "./actions/use.js";
import {getAction} from "./actions/api.js";

export function init() {

    let getSpeed = actor => actor?.system?.attributes?.movement?.walk || 0;

    const isDM = () => game.user.isGM;

    // === Хуки ===
    Hooks.on("combatTurn", async (combat, combatant) => {
        console.log(combat, combatant, game);
        if (!isDM()) return;

        let token = canvas.tokens.objects.children.filter(token=>token.id===game.combat.nextCombatant.tokenId)[0];
        if (!token) return console.log('no tokens');

        console.log(token);
        let data = {};
        data.speed = getSpeed(token.actor);
        data.step = canvas.grid.size;
        data.disposition = token.document?.disposition ?? 0;

        // ---------- 1. Персонажи, которых видит токен ----------
        const visibleTokens = [];
        for (let otherToken of canvas.tokens.placeables) {
            if (otherToken.id === token.id) continue;

            let hasLineOfSight = false;
            try {
                const sightBackend = CONFIG.Canvas.polygonBackends?.sight;
                if (sightBackend && typeof sightBackend.testCollision === "function") {
                    const collision = sightBackend.testCollision({
                        type: "sight",
                        source: token.center,
                        destination: otherToken.center,
                        mode: "any"
                    });
                    hasLineOfSight = !collision;
                } else {
                    // Старый метод как fallback
                    const ray = new Ray(token.center, otherToken.center);
                    const collision = canvas.walls.checkCollision(ray, { type: "sight", mode: "any" });
                    hasLineOfSight = !collision;
                }
            } catch(e) {
                console.warn(`Ошибка проверки видимости для ${otherToken.name}:`, e);
                hasLineOfSight = true;
            }

            if (!hasLineOfSight) continue;

            const actorData = otherToken.actor;
            if (!actorData) continue;

            let equippedWeapon = null;
            const weapon = actorData.items.find(i => i.type === "weapon" && i.system.equipped);
            if (weapon) equippedWeapon = weapon.name;

            const ac = actorData.system.attributes.ac?.value || 10;

            visibleTokens.push({
                id: otherToken.id,
                name: otherToken.name,
                disposition: otherToken.document?.disposition ?? 0,
                x: otherToken.x,
                y: otherToken.y,
                weapon: equippedWeapon,
                ac: ac
            });
        }

        // Группировка по отношению к текущему токену
        const currentDisposition = token.document?.disposition ?? 0;
        const friends = [];
        const enemies = [];
        const neutrals = [];

        for (const t of visibleTokens) {
            if (t.disposition === 0) {
                neutrals.push(t);
            } else if (t.disposition === currentDisposition) {
                friends.push(t);
            } else {
                enemies.push(t);
            }
        }

        data.visibleTokens = visibleTokens;   // общий список (опционально)
        data.friends = friends;
        data.enemies = enemies;
        data.neutrals = neutrals;

        // ---------- 2. Доступные действия (способности) ----------
        const availableActions = [];
        for (let item of token.actor.items) {
            // Типы предметов, которые могут быть использованы в бою
            if (item.type === "weapon" || item.type === "spell" || item.type === "feat" || item.type === "consumable") {
                // Базовая информация
                const action = {
                    id: item.id,
                    name: item.name,
                    type: item.type,
                    uses: item.system.uses?.value || null,
                    maxUses: item.system.uses?.max || null,
                    recharge: item.system.recharge?.value || null,
                    range: item.system.range?.value || null,
                    damage: item.system.damage?.parts?.[0]?.[0] || null,
                    description: item.system.description?.value?.substring(0, 200) || ""
                };

                // Для оружия добавим тип броска и бонус атаки
                if (item.type === "weapon") {
                    action.attackBonus = item.system.attackBonus || 0;
                    action.properties = item.system.properties || {};
                }

                // Для заклинаний - уровень и школу
                if (item.type === "spell") {
                    action.level = item.system.level || 0;
                    action.school = item.system.school || "";
                }

                availableActions.push(action);
            }
        }
        // Можно отсортировать по значимости (оружие ближнего боя, затем заклинания)
        availableActions.sort((a,b) => (a.type === "weapon" && b.type !== "weapon") ? -1 : 1);
        data.availableActions = availableActions;

        // ---------- 3. Передаём данные нейросети ----------

        console.log(data);
        let actions = getAction(data);

        for (const item of actions) {
            let action = item.action;
            let conf = item.conf;

            // Выполняем действия
            if (action === 'move') {
                await move(token, conf);
            }
            if (action === 'target') {
                target(token, conf);
            }
            if (action === 'use') {
                use(token, conf);
            }
        }

    });
}