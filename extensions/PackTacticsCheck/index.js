
export function init() {
    console.log("Pack Tactics | ИНИЦИАЛИЗАЦИЯ СКРИПТА");

    // ========== ПРОВЕРКА НАЛИЧИЯ СПОСОБНОСТИ ==========
    function hasPackTacticsAbility(actor) {
        if (!actor?.items) {
            console.log(`Pack Tactics | [${actor?.name}] Нет items — не могу проверить способность`);
            return false;
        }
        const found = actor.items.some(item =>
            item.type === "feat" &&
            (item.name.toLowerCase().includes("тактик") && item.name.toLowerCase().includes("стаи")) ||
            item.name.toLowerCase().includes("pack tactics")
        );
        console.log(`Pack Tactics | [${actor.name}] имеет способность "Тактика стаи"? ${found}`);
        return found;
    }

    // ========== ПОИСК ЭФФЕКТА ==========
    function findPackTacticsEffect(actor) {
        const effect = actor.effects.find(e =>
            e.name.toLowerCase().includes("тактика стаи") ||
            e.name.toLowerCase().includes("pack tactics")
        );
        console.log(`Pack Tactics | [${actor.name}] активный эффект: ${effect ? effect.name : "нет"}`);
        return effect;
    }

    // ========== ПРОВЕРКА СОЮЗНИКОВ РЯДОМ С ЦЕЛЬЮ ==========
    function hasAlliesNearTarget(targetToken, attackerToken) {
        if (!targetToken || !attackerToken) {
            console.log(`Pack Tactics | Ошибка: нет токена цели или атакующего`);
            return false;
        }

        const attackerDisposition = attackerToken.document.disposition;
        console.log(`Pack Tactics | Disposition атакующего (${attackerToken.name}): ${attackerDisposition}`);

        const rangeFeet = 7.5; // 1 клетка
        let alliesCount = 0;

        for (let token of canvas.tokens.placeables) {
            if (token.id === targetToken.id) continue;      // не сама цель
            if (token.id === attackerToken.id) continue;    // не сам атакующий
            if (!token.actor || token.actor.system.attributes?.hp?.value <= 0) continue; // мёртвых не берём
            if (token.document.disposition !== attackerDisposition) continue; // только союзники

            const distance = canvas.grid.measureDistance(targetToken, token);
            if (distance <= rangeFeet) {
                alliesCount++;
                console.log(`Pack Tactics | Союзник рядом с целью: ${token.name} (дистанция ${distance} футов)`);
            }
        }

        const result = alliesCount > 0;
        console.log(`Pack Tactics | У цели ${targetToken.name} есть союзник в 5 футах? ${result} (найдено ${alliesCount})`);
        return result;
    }

    // ========== УСТАНОВКА / УДАЛЕНИЕ ЭФФЕКТА ==========
    async function setPackTacticsEffect(actor, token, enable) {
        const existing = findPackTacticsEffect(actor);
        if (enable && !existing) {
            console.log(`Pack Tactics | СОЗДАЮ ЭФФЕКТ для ${actor.name}`);
            const effectData = {
                name: "Тактика стаи",
                icon: "icons/creatures/abilities/paw-print-orange.webp",
                origin: actor.uuid,
                disabled: false,
                duration: { rounds: 1, startRound: game.combat?.round, startTurn: game.combat?.turn, seconds: 6 },
                changes: [
                    { key: "flags.midi-qol.advantage.attack.all", mode: CONST.ACTIVE_EFFECT_MODES.OVERRIDE, value: true, priority: 20 },
                    { key: "flags.dnd5e.advantage.attack.all", mode: CONST.ACTIVE_EFFECT_MODES.OVERRIDE, value: true, priority: 10 }
                ],
                flags: { core: { statusId: "packTactics" }, dae: { specialDuration: ["turnEnd"], stackable: false } }
            };
            await actor.createEmbeddedDocuments("ActiveEffect", [effectData]);
            if (token?.isVisible) {
                token.animate({ attribute: "alpha", to: 0.5, duration: 200 }).then(() =>
                    token.animate({ attribute: "alpha", to: 1.0, duration: 200 })
                );
            }
        }
        else if (!enable && existing) {
            console.log(`Pack Tactics | УДАЛЯЮ ЭФФЕКТ у ${actor.name}`);
            await existing.delete();
        } else {
            console.log(`Pack Tactics | Действие не требуется (enable=${enable}, existing=${!!existing})`);
        }
    }

    // ========== ОСНОВНАЯ ЛОГИКА ПРИ ВЫБОРЕ ЦЕЛИ ==========
    async function onTargetSelected(user, targetToken, targeted) {
        console.log(`Pack Tactics | СОБЫТИЕ targetToken: user=${user.name}, target=${targetToken?.name}, targeted=${targeted}`);

        if (!targeted) {
            console.log("Pack Tactics | Игнорирую снятие цели");
            return;
        }
        if (!targetToken?.actor) {
            console.log("Pack Tactics | Цель не имеет актёра, игнорирую");
            return;
        }

        const currentTokenDoc = game.combat?.current;
        const combatToken = currentTokenDoc ? canvas.tokens.get(currentTokenDoc.tokenId) : null;
        const selectedTokens = canvas.tokens.controlled;
        let attackerToken = null;

        if (selectedTokens.length > 0) {
            attackerToken = selectedTokens[0];
        } else if (combatToken) {
            attackerToken = combatToken;
        }

        if (!attackerToken) {
            console.log("Pack Tactics | У пользователя нет выбранных токенов и нет текущего combatant");
            return;
        }

        console.log(`Pack Tactics | Атакующий: ${attackerToken.name} (ID ${attackerToken.id})`);
        const attackerActor = attackerToken.actor;

        if (!attackerActor) {
            console.log("Pack Tactics | У атакующего токена нет актёра");
            return;
        }

        if (!hasPackTacticsAbility(attackerActor)) {
            console.log("Pack Tactics | У атакующего нет способности, выхожу");
            return;
        }

        const hasAllies = hasAlliesNearTarget(targetToken, attackerToken);
        await setPackTacticsEffect(attackerActor, attackerToken, hasAllies);
    }

    // ========== НАЧАЛО ХОДА: ПРОВЕРЯЕМ ЦЕЛЬ И АКТИВИРУЕМ ЭФФЕКТ ==========
    async function onCombatTurn(combat, combatant) {
        console.log(`Pack Tactics | СОБЫТИЕ combatTurn: ход ${combatant?.name} начинается`);
        await new Promise(resolve => setTimeout(resolve, 500));

        const currentTokenDoc = game.combat.current;
        if (!currentTokenDoc) return log.info('no current combatant');

        const token = canvas.tokens.get(currentTokenDoc.tokenId);
        if (!token?.actor) return;
        if (!hasPackTacticsAbility(token.actor)) return;

        const targets = Array.from(game.user.targets);
        if (targets.length === 0) {
            console.log("Pack Tactics | Нет активных целей, эффект не активирую");
            await setPackTacticsEffect(token.actor, token, false);
            return;
        }
        const targetToken = targets[0];
        const hasAllies = hasAlliesNearTarget(targetToken, token);
        await setPackTacticsEffect(token.actor, token, hasAllies);
    }

    // ========== КОНЕЦ ХОДА: УДАЛЯЕМ ЭФФЕКТ ==========
    async function onCombatTurnEnd(combat, combatant) {
        console.log(`Pack Tactics | СОБЫТИЕ combatTurnEnd: ход ${combatant?.name} закончился`);
        if (!combatant?.token) {
            console.log("Pack Tactics | Нет токена у combatant");
            return;
        }
        const token = canvas.tokens.get(combatant.token.id);
        if (!token?.actor) {
            console.log("Pack Tactics | Не найден токен или актёр");
            return;
        }
        const actor = token.actor;
        if (!hasPackTacticsAbility(actor)) {
            console.log(`Pack Tactics | У ${actor.name} нет тактики стаи, выхожу`);
            return;
        }
        const effect = findPackTacticsEffect(actor);
        if (effect) {
            console.log(`Pack Tactics | Удаляю эффект после окончания хода ${actor.name}`);
            await effect.delete();
        } else {
            console.log(`Pack Tactics | Эффекта не было, ничего не делаю`);
        }
    }

    // ========== РЕГИСТРАЦИЯ ХУКОВ ==========
    Hooks.on("targetToken", onTargetSelected);
    Hooks.on("combatTurn", onCombatTurn);
    Hooks.on("combatRound", onCombatTurn);
    Hooks.on("combatTurnEnd", onCombatTurnEnd);
    console.log("Pack Tactics | Все хуки зарегистрированы. Теперь выбирай цель за НПС — смотри консоль F12");
}