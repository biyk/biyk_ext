import {move} from "./actions/move.js";
import {target} from "./actions/target.js";
import {use} from "./actions/use.js";
import {getAction} from "./actions/api.js";
import {sendMessage} from "./actions/message.js";
import {getStatus, buildItemAction} from "./utils/help.js";
import {getCurrentTokenData, getVisibleCombatTokens, groupTokensByDisposition} from "./utils/combat.js";
import {log} from "./utils/logger.js";
import {addGMButton} from "./utils/messageBox.js";

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

        if (data.disposition===-2) {//это или босс или ДМский персонаж
            //генерируем и показываем для ДМ окошко с советом от Нейросети
            let message = JSON.stringify(actions);

            for (const item of actions) {
                const action = item.action;
                const conf = item.conf;

                try {
                    if (action === 'target') {
                        target(token, conf);
                        await new Promise(resolve => setTimeout(resolve, 500));
                    }

                }catch (e) {
                    return console.error(e);
                }
            }
            if (game.user.isGM) {
                new Dialog({
                    title: "Сообщение для ГМ",
                    content: `<p>${message}</p>`,
                    buttons: {
                        ok: {
                            icon: '<i class="fas fa-check"></i>',
                            label: "OK",
                            callback: () => console.log("Окно закрыто")
                        }
                    },
                    default: "ok"
                }).render(true);
            }
        }else {
            for (const item of actions) {
                const action = item.action;
                const conf = item.conf;

                try {
                    if (action === 'move') {
                        if(!limit.move) continue
                        await move(token, conf);
                        limit.move--;
                    }
                    if (action === 'target') {
                        target(token, conf);
                        await new Promise(resolve => setTimeout(resolve, 500));
                    }
                    if (action === 'use') {
                        if(!limit.use) continue
                        if (conf){
                            for (let item of token.actor.items) {
                                if (item['_id']===conf.itemId && item.name.toLowerCase().includes("рывок")){
                                    limit.move+=data.baseMove
                                }
                            }
                        }
                        await use(token, conf);
                        limit.use--;
                    }
                    if (action === 'message') await sendMessage(token, conf);
                }catch (e) {
                    return console.error(e);
                }
            }
            game.combat.nextTurn();
        }

        ui.notifications.warn(`Ход завершен!`);
    }

    // === Хуки ===
    Hooks.on("updateCombat", async (combat, combatant) => {
        await combatTurn()
    });
    Hooks.on("combatRound", async (combat, combatant) => {
        await combatTurn()
    });

    addGMButton();

    Hooks.on("renderCombatTracker", (app, html, data) => {
        // Ваша функция addGMButton, но с поиском кнопки внутри текущего html
        if (html.find("#custom-text-save-btn").length) return;
        addGMButton();
    });
}