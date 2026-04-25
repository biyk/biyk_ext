import {move} from "./actions/move.js";
import {target} from "./actions/target.js";
import {use} from "./actions/use.js";
import {getAction} from "./actions/api.js";
import {sendMessage} from "./actions/message.js";
import {getStatus, buildItemAction} from "./utils/help.js";
import {getCurrentTokenData, getVisibleCombatTokens, groupTokensByDisposition} from "./utils/combat.js";

export function init() {

    const isDM = () => game.user.isGM;

    async function combatTurn() {
        if (!isDM()) return;
        await new Promise(resolve => setTimeout(resolve, 500));

        const currentTokenDoc = game.combat.current;
        if (!currentTokenDoc) return console.log('no current combatant');

        const token = canvas.tokens.get(currentTokenDoc.tokenId);
        if (!token) return console.log('no token');

        if (token.actor?.system?.attributes?.hp == 0) return console.log('Актер мертв');
        if (token.actor?.type !== 'npc') return console.log('это не НПС');

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
        for (let item of token.actor.items) {
            if (item.type === "weapon" || item.type === "spell" || item.type === "feat" || item.type === "consumable") {
                availableActions.push(buildItemAction(item));
            }
        }
        availableActions.sort((a, b) => (a.type === "weapon" && b.type !== "weapon") ? -1 : 1);
        data.availableActions = availableActions;

        // ---------- 4. Запрос к ИИ ----------
        console.log(data);
        let actions = await getAction(data);

        let limit = {
            move: data.baseMove,
            use: 1,
            bonus: 1,
            target: 1
        };

        // ---------- 5. Выполнение действий ----------
        for (const item of actions) {
            const action = item.action;
            const conf = item.conf;

            if (action === 'move') await move(token, conf);
            if (action === 'target') target(token, conf);
            if (action === 'use') await use(token, conf);
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