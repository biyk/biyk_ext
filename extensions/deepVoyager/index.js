import {move} from "./actions/move.js";
import {target, clearTargets} from "./actions/target.js";
import {use} from "./actions/use.js";
import {getAction} from "./actions/api.js";
import {sendMessage} from "./actions/message.js";
import {getStatus, buildItemAction, buildWeapons, npcSimFields} from "./utils/help.js";
import {getCurrentTokenData, getVisibleCombatTokens, groupTokensByDisposition} from "./utils/combat.js";
import {log} from "./utils/logger.js";
import {addGMButton} from "./utils/messageBox.js";
import {getMovementRose} from "./utils/tokenInfo.js";

export function init() {

    const isDM = () => game.user.isGM;

    let lastCombatTurnTime = 0;
    const COMBAT_TURN_THROTTLE = 500; // 0.5 с (дубли-вход и так закрыт флагом turnInProgress)

    async function combatTurn() {
        if (!isDM()) return;

        const now = Date.now();
        if (now - lastCombatTurnTime < COMBAT_TURN_THROTTLE) {
            log.info('CombatTurn заблокирован (throttle)');
            return;
        }
        lastCombatTurnTime = now;

        // --- [turn-prof] пофазный замер хода (только логирование, поведение не меняем) ---
        const _p0 = performance.now();
        let _pl = _p0;
        const _P = (n) => { const t = performance.now();
            log.info(`[turn-prof] ${n}: +${(t - _pl).toFixed(0)}мс (всего ${(t - _p0).toFixed(0)}мс)`);
            _pl = t; };

        await new Promise(resolve => setTimeout(resolve, 150));
        _P('сон-старт (150мс)');

        const currentTokenDoc = game.combat.current;
        if (!currentTokenDoc) return log.info('no current combatant');

        const token = canvas.tokens.get(currentTokenDoc.tokenId);

        if (!token) return log.info('no token');

        // Смерть проверяем по hp.value: attributes.hp — объект, и сравнение его с 0 никогда
        // не срабатывало, из-за чего кнопка заставляла ходить мёртвого бойца.
        if ((token.actor?.system?.attributes?.hp?.value ?? 1) <= 0) {
            log.info('Актер мертв');
            await game.combat.nextTurn();
            return ui.notifications.warn(`${token.name}: мёртв, ход передан дальше`);
        }
        if (token.actor?.type !== 'npc') return log.info('это не НПС');
        log.info(token);

        // Цели прошлых ходов не наследуем: dnd5e/midi-qol бьют по game.user.targets
        // (общее состояние GM), а не по «цели актёра». Оставшаяся цель — часто сам
        // этот боец (его били в прошлом ходу) — иначе превращает его атаку в удар по себе.
        clearTargets(`начало хода ${token.name}`);

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
        data.movement = await getMovementRose(token);
        _P('видимые токены+действия+rose (сбор данных)');
        //console.log(data);return ;

        // ---------- 4. Запрос к ИИ ----------
        log.info('============>Отправляю запрос',data.name);
        // Пункт 4: сначала собственный расчёт /plan (первый видимый враг + всё equipped-оружие,
        // сервер сам выбирает чем и с какой клетки бить), пустой план/ошибка — прежний путь LLM.
        let actions = [];
        if (data.disposition !== -2) {
            const enemy = data.enemies[0];
            const weapons = buildWeapons(token);
            log.info('вооружение:', weapons.map(w => `${w.name} ${w.sureFt}/${w.doubtFt}ф`
                + `${w.properties?.includes('thr') ? ' (метат)' : (w.ranged ? ' (дальнобой)' : '')}`));
            actions = await api.getPlanActions(token, enemy ? enemy.id : null, currentData.speed, weapons);
            _P('запрос /plan (+сбор getAllData + RTT + инференс)');
        }
        if (!actions.length) { actions = await getAction(data); _P('fallback /ask (LLM)'); }

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
                        await new Promise(resolve => setTimeout(resolve, 200));
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
        } else {
            // План может прийти от LLM в любом порядке, поэтому цель ищем по всем действиям
            // хода: use() ставит её явно, чтобы атака не ушла в «висящую» цель прошлого хода.
            const plannedTargetId = actions.find(a => a.action === 'target'
                && a.conf?.id && a.conf.id !== token.id)?.conf?.id ?? null;

            for (const item of actions) {
                const action = item.action;
                const conf = item.conf;

                try {
                    //log.info('do action - ' + action);
                    if (action === 'move') {
                        if(limit.move <=0) continue
                        let moving = await move(token, conf);
                        if(moving!==true){//если ИИ затупил двигаем в сторону последней цели
                            log.info(moving);
                            log.info("ИИшка затупила сами");
                            let currentToken = token;
                            
                            let using = actions.filter(e=>e.action==='use').length;
                            if (!using) {
                                for (let item of token.actor.items) {
                                    if (item.name.toLowerCase().includes("рывок")){
                                        await item.use();
                                        limit.move+=data.baseMove
                                    }
                                }
                            }
                            const plannedTarget = plannedTargetId ? canvas.tokens.get(plannedTargetId) : null;
                            const targets = (plannedTarget ? [plannedTarget] : Array.from(game.user.targets))
                                .filter(t => t && t.id !== token.id);
                            if (targets.length > 0) {
                                let targetToken = targets[0];
                                let response = await api.sendRequest(currentToken, targetToken)

                                let path = response.path || []

                                log.info(path);
                                if (path.length > 0) {
                                    for (const direction of path) {
                                        let moving = await move(currentToken, {direction})
                                        log.info('Двигаюсь', direction);
                                        limit.move--;
                                        if (moving!==true  || limit.move <=0) {
                                            log.info(`Дальнейшее передвижение невозможно ${limit.move}`);
                                            break;
                                        }
                                    }
                                } else {
                                    //return ui.notifications.warn(`ДМ - нужно ходить за НПС`);
                                }

                            } else {
                                log.info("Нет целей");
                            }
                        }
                        limit.move--;
                    }
                    if (action === 'target') {
                        target(token, conf);
                        await new Promise(resolve => setTimeout(resolve, 200));
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
                        const used = await use(token, conf, plannedTargetId);
                        // Пропущенная атака (нет цели) не тратит лимит use: план может содержать
                        // ещё одно действие, и оно должно остаться доступным.
                        if (used) limit.use--;
                    }
                    if (action === 'message') await sendMessage(token, conf);
                    _P('действие: ' + action);
                }catch (e) {
                    console.error(e);
                }
            }
            await new Promise(resolve => setTimeout(resolve, 1200));
            _P('сон-финал (1200мс)');
            game.combat.nextTurn();
            _P('nextTurn (перерисовка трекера)');
        }

        ui.notifications.warn(`Ход завершен!`);
    }

    // === Хуки ===

    // Обёртка ручного хода (кнопка ▶ / api.combatTurn из консоли): защита от повторного входа.
    let turnInProgress = false;

    async function manualCombatTurn() {
        if (turnInProgress) return log.info('Ход уже выполняется, не торопи');
        turnInProgress = true;
        try {
            await combatTurn();
        } catch (e) {
            console.error(e);
        } finally {
            turnInProgress = false;
        }
    }

    Hooks.on("updateCombat", async (combat, combatant) => {
        //await combatTurn()
    });
    Hooks.on("combatRound", async (combat, combatant) => {
        //await combatTurn()
    });

    addGMButton(manualCombatTurn);

    Hooks.on("renderCombatTracker", (app, html, data) => {
        // Ваша функция addGMButton, но с поиском кнопки внутри текущего html
        if (html.find("#custom-text-save-btn").length) return;
        addGMButton(manualCombatTurn);
    });



    // Создаём API объект
    const api = {
        // Собственный расчёт хода (сервер /plan, пункт 4 todo.md). Ошибка/пусто -> [].
        // weapons — массив вооружения токена (см. utils/help.js buildWeapons).
        getPlanActions: async (srcToken, targetId, speed, weapons) => {
            try {
                const data = api.getAllData();
                const response = await fetch('http://localhost:9999/plan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json; charset=utf-8' },
                    body: JSON.stringify({ src: srcToken.id, token: targetId, speed, weapons, data }),
                }).then(r => r.json());

                if (response.error) log.error('plan:', response.error);
                log.info('plan actions:', response.actions || []);
                return response.actions || [];
            } catch (e) {
                log.error('Сервер :9999/plan недоступен', e);
                return [];
            }
        },

        testPath: async () => {
            const selected = canvas.tokens.controlled;
            let currentToken = null;
            let targetToken = null;

            if (selected.length >= 2) {
                // Если выбрано 2+ токенов: первый – текущий, второй – целевой
                currentToken = selected[0];
                targetToken = selected[1];
            } else if (selected.length === 1) {
                // Если выбран один токен – он текущий, цель берём из game.user.targets
                currentToken = selected[0];
                const targets = Array.from(game.user.targets);
                if (targets.length === 0) {
                    throw new Error("Не выбран целевой токен: либо выберите два токена, либо выберите цель после выбора своего токена");
                }
                targetToken = targets[0];
            } else {
                throw new Error("Не выбран текущий токен (выделите хотя бы один токен)");
            }

            if (!currentToken || !targetToken) {
                throw new Error("Не удалось определить текущий или целевой токен");
            }
            let response = await api.sendRequest(currentToken, targetToken)

            let path = response.path || []

            console.log(path);
            for (const direction of path) {
                let moving = await move(currentToken, {direction})
                console.log('Двигаюсь', direction);
                if (moving!==true) {
                    console.error('Дальнейшее передвижение невозможно');
                    break;
                }
            }

        },
        move: move,
        sendRequest: async (src, token) => {

            const AI_API_URL = 'http://localhost:9999/path'
            //получение данных
            let data = api.getAllData();
            let response = await fetch(AI_API_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json; charset=utf-8' },
                body: JSON.stringify({ src:src.id, token:token.id, data }),
            }).then(r => r.json());

            return response;



        },
        getAllData: () => {
            const scene = canvas.scene;
            if (!scene) {
                console.error("Нет активной сцены");
                return;
            }

            // 1. Сбор NPC токенов
            // Инициатива из активного боя: сервер иначе перекидывает врагам d20 на каждый /plan,
            // а тренировочный контракт ожидает стабильное поле initiative у каждого npc.
            const iniByToken = new Map();
            const combatants = game.combat?.combatants?.contents ?? game.combat?.combatants ?? [];
            for (const c of combatants) {
                if (c.tokenId && Number.isFinite(Number(c.initiative))) {
                    iniByToken.set(c.tokenId, Number(c.initiative));
                }
            }
            const npcs = [];
            for (let token of canvas.tokens.placeables) {
                const actor = token.actor;
                // считаем NPC: если актёр существует и его тип !== 'character' (или === 'npc')
                if (actor) {
                    // Уточнение: в D&D 5e тип может быть 'npc', 'character' – игроки обычно 'character' и имеют владельца-игрока
                    // Для большей точности: считаем NPC, если актёр не имеет владельца-игрока (или имеет владельца с ролью GM)
                    const isPlayer = actor.hasPlayerOwner && !actor.owners?.filter?.(o => o.role === 4).length ? false : true; // проще: не используем hasPlayerOwner, а проверяем наличие игроков-владельцев
                    // Лучше: если у актёра есть хотя бы один владелец с ролью < GM (игрок), то это игрок
                    let isPlayerControlled = false;
                    for (let user of game.users) {
                        if (user.isGM) continue;
                        if (actor.testUserPermission(user, "OWNER")) {
                            isPlayerControlled = true;
                            break;
                        }
                    }
                    if (!isPlayerControlled || 1) {
                        // Это NPC
                        const hp = actor.system.attributes?.hp || {};
                        npcs.push({
                            id: token.id,
                            name: token.name,
                            // document.x/y согласованы с center (тоже от документа): раньше в
                            // одном объекте жили две разные клетки, если канвас не успел перерисоваться.
                            x: token.document.x,
                            y: token.document.y,
                            width: token.w,
                            height: token.h,
                            center: { x: token.center.x, y: token.center.y },
                            disposition: token.document.disposition,
                            hp: {
                                current: hp.value,
                                max: hp.max,
                                temp: hp.temp
                            },
                            ...npcSimFields(token, iniByToken.get(token.id))
                        });
                    }
                }
            }

            // 2. Сбор стен, дверей, окон
            const walls = [];
            for (let wall of canvas.walls.placeables) {
                const wallData = {
                    id: wall.id,
                    points: {
                        A: { x: wall.document.c[0], y: wall.document.c[1] },
                        B: { x: wall.document.c[2], y: wall.document.c[3] }
                    },
                    type: "wall", // по умолчанию
                    door: null,
                    closed: false,
                    locked: false
                };
                // Определяем тип: дверь (door) или окно (window)
                if (wall.document.door) {
                    wallData.type = "door";
                    wallData.closed = wall.document.ds === 1; // 1 = closed? Нужно уточнить
                    wallData.locked = wall.document.dl === true; // locked?
                    // В Foundry v11: wall.document.doorState (0=closed, 1=open, 2=locked)
                    if (wall.document.doorState !== undefined) {
                        wallData.closed = wall.document.doorState === 0;
                        wallData.locked = wall.document.doorState === 2;
                    }
                } else if (wall.document.window) {
                    wallData.type = "window";
                }
                // Можно добавить информацию о движении и обзоре: move и sight
                wallData.move = wall.document.move;
                wallData.sight = wall.document.sight;
                walls.push(wallData);
            }

            const result = {
                scene: {
                    id: scene.id,
                    name: scene.name,
                    width: scene.dimensions.width,
                    height: scene.dimensions.height,
                    gridSize: canvas.grid.size
                },
                npcs: npcs,
                walls: walls
            };

            // Выводим в консоль удобно
            //console.log("=== Собранные данные ===");
            //console.log(JSON.stringify(result, null, 2));
            // Также можно скопировать в буфер обмена (не обязательно)
            //copy(JSON.stringify(result, null, 2));
            return result;
        },
        // другие функции
    };

    // Сохраняем API в глобальный объект модуля
    api.combatTurn = manualCombatTurn; // ручной запуск хода из консоли: game.modules.get("biyk_ext").api.combatTurn()
    game.modules.get("biyk_ext").api = api;
}