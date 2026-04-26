import {move} from "./actions/move.js";
import {target} from "./actions/target.js";
import {use} from "./actions/use.js";
import {getAction} from "./actions/api.js";
import {sendMessage} from "./actions/message.js";
import {getStatus, buildItemAction} from "./utils/help.js";
import {getCurrentTokenData, getVisibleCombatTokens, groupTokensByDisposition} from "./utils/combat.js";
import {log} from "./utils/logger.js";

export function init() {

    const isDM = () => game.user.isGM;

    async function combatTurn() {
        if (!isDM()) return;
        await new Promise(resolve => setTimeout(resolve, 500));

        const currentTokenDoc = game.combat.current;
        if (!currentTokenDoc) return log.info('no current combatant');

        const token = canvas.tokens.get(currentTokenDoc.tokenId);
        if (!token) return log.info('no token');

        if (token.actor?.system?.attributes?.hp == 0) return log.info('Актер мертв');
        if (token.actor?.type !== 'npc') return log.info('это не НПС');
        if (game.paused) return log.info('игра на паузе');
        log.info(token);

        // ---------- 1. Данные текущего токена ----------
        const currentData = getCurrentTokenData(game.combat, currentTokenDoc);
        const data = {
            name: currentData.name,
            x: currentData.x,
            y: currentData.y,
            speed: currentData.speed,
            step: currentData.step,
            baseMove: currentData.speed / 5,
            status: currentData.status,
            languages: currentData.languages,
            disposition: currentData.disposition
        };

        // ---------- 2. Видимые токены из боя ----------
        const visibleTokens = getVisibleCombatTokens(token);
        const grouped = groupTokensByDisposition(visibleTokens, data.disposition);

        data.friends = grouped.friends;
        data.enemies = grouped.enemies;
        data.neutrals = grouped.neutrals;

        // ---------- 3. Доступные действия ----------
        const availableActions = [];
        const availableFeats = [];

        for (let item of token.actor.items) {
            if (
                ((item.type === "weapon"  || item.type === "equipment") && item.system.equipped) ||
                item.type === "spell"||
                item.type === "consumable") {
                availableActions.push(buildItemAction(item));
            }

            if (item.type === "feat" && item.effects?.size){
                for (let effect of item.effects) {
                    availableFeats.push({name:effect.name, enabled:!effect.disabled});
                }
            }
        }
        availableActions.sort((a, b) => (a.type === "weapon" && b.type !== "weapon") ? -1 : 1);
        data.availableActions = availableActions;
        data.availableFeats = availableFeats;

        // ---------- 4. Запрос к ИИ ----------
        log.info(data);
        let actions = await getAction(data);

        let limit = {
            move: data.baseMove,
            use: 1,
            bonus: 1,
            target: 1
        };

        log.info(actions);
        // ---------- 5. Выполнение действий ----------
        for (const item of actions) {
            const action = item.action;
            const conf = item.conf;

            if (action === 'move') await move(token, conf);
            if (action === 'target') target(token, conf);
            if (action === 'use') {
                if (conf){
                    let item = token.actor.items.get(conf.itemId)
                    if (item.name.toLowerCase().includes("рывок")){
                        limit.move+=data.baseMove
                    }
                }
                await use(token, conf);
            }
            if (action === 'message') await sendMessage(token, conf);
        }

        ui.notifications.warn(`Ход завершен!`);
        game.combat.nextTurn();
    }

    // === Хуки ===
    Hooks.on("combatTurn", async (combat, combatant) => {
        await combatTurn()
    });
    Hooks.on("combatRound", async (combat, combatant) => {
        await combatTurn()
    });
}