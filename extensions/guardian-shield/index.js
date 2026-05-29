export function init() {
    const PREFIX = "⚔️[Щит Хранителя]";
    console.log(`${PREFIX} Скрипт загружен`);
    if (!game.modules.get("midi-qol")?.active) {
        console.error(`${PREFIX} midi-qol не активен!`);
        return;
    }
    console.log(`${PREFIX} midi-qol версия:`, game.modules.get("midi-qol").version);

    // Главный хук (с большой буквы D!) – вызывается после расчёта урона, перед применением к целям
    Hooks.on("midi-qol.DamageRollComplete", async (workflow) => {
        console.log(`${PREFIX} === DamageRollComplete ===`);
        if (!workflow?.damageTotal || workflow.damageTotal <= 0) {
            console.log(`${PREFIX} Урон = 0, выход`);
            return;
        }
        if (!workflow.targets || workflow.targets.size === 0) {
            console.log(`${PREFIX} Нет целей, выход`);
            return;
        }

        const currentRound = game.combat?.round ?? 0;
        const damageTotal = workflow.damageTotal;
        console.log(`${PREFIX} Раунд ${currentRound}, урон ${damageTotal}, цели:`, Array.from(workflow.targets).map(t => t.name));

        // Перебираем цели (копируем Set в массив, так как будем удалять элементы)
        const targetsArray = Array.from(workflow.targets);
        for (const targetToken of targetsArray) {
            console.log(`${PREFIX} --- Проверяем цель: ${targetToken.name} ---`);
            if (!targetToken?.actor) continue;

            // Поиск хранителей
            let useItem;
            const guardians = canvas.tokens.placeables.filter(t => {
                if (!t.actor) return false;
                if (t.actor.id === targetToken.actor.id) return false;
                if (t.document?.disposition !== targetToken.document?.disposition) return false;
                const dist = MidiQOL.getDistance(t, targetToken, false);
                if (dist === null || dist > 30) return false;

                const canSee = MidiQOL.canSense
                    ? MidiQOL.canSense(t.document, targetToken.document)
                    : canvas.sight.testVisibility(t, { object: targetToken });
                if (!canSee) {
                    console.log(`${PREFIX}   ${t.name} не видит цель`);
                    return false;
                }

                const hasItem = t.actor.items.find(i => i.name === "Проведение энергии: Щит хранителя");

                if (!hasItem) {
                    console.log(`${PREFIX}   ${t.name} не имеет заклинания`);
                    return false;
                }

                useItem = t.actor.items.find(i => i.name.includes("Проведение энергии"));
                let uses = useItem?.system.uses.value;
                if (!uses) {
                    console.log(`${PREFIX}   ${useItem.name} закончились заряды`);
                    return false;
                }

                const midiActions = t.actor.getFlag("midi-qol", "actions") || {};
                const reaction = midiActions.reaction;
                if (reaction && reaction.round === currentRound) {
                    console.log(`${PREFIX}   ${t.name} уже использовал реакцию`);
                    return false;
                }

                console.log(`${PREFIX}   >> ${t.name} ПОДХОДИТ!`);
                return true;
            });

            console.log(`${PREFIX} Найдено хранителей: ${guardians.length}`);
            if (guardians.length === 0) continue;

            const guardianToken = guardians[0];
            const guardianActor = guardianToken.actor;
            console.log(`${PREFIX} Хранитель: `, guardianActor);


            // Диалог
            const useReaction = await Dialog.confirm({
                title: "Проведение энергии: Щит хранителя",
                content: `<p><strong>${guardianActor.name}</strong>, использовать <b>реакцию</b> и принять урон (${damageTotal}) за <strong>${targetToken.name}</strong>?<br>Будет получена половина урона (устойчивость).</p>`
            });
            console.log(`${PREFIX} Результат диалога: ${useReaction}`);

            if (!useReaction) {
                console.log(`${PREFIX} Отказ, пропускаем`);
                continue;
            }

            // Тратим реакцию
            let midiActions = guardianActor.getFlag("midi-qol", "actions") || {};
            midiActions = foundry.utils.mergeObject(midiActions, {
                reaction: { round: currentRound }
            });
            await guardianActor.setFlag("midi-qol", "actions", midiActions);
            console.log(`${PREFIX} Реакция ${guardianActor.name} потрачена`);

            //TODO уменьшаяем использование useItem
            if (useItem) {
                const currentUses = useItem.system.uses.value;
                if (currentUses > 0) {
                    await useItem.update({ "system.uses.value": currentUses - 1 });
                    console.log(`${PREFIX} Заряд «Проведения энергии» уменьшен до ${currentUses - 1}`);
                }
            }

            // Убираем защищённую цель из списка получателей урона
            workflow.targets.delete(targetToken);
            console.log(`${PREFIX} Цель ${targetToken.name} удалена из workflow.targets`);

            const halfDamage = Math.floor(damageTotal / 2);
            ChatMessage.create({
                speaker: { actor: guardianActor },
                content: `<b>${guardianActor.name}</b> использует <em>«Щит хранителя»</em> и принимает урон за <b>${targetToken.name}</b>.<br>Исходный урон ${damageTotal} → получает ${halfDamage} (устойчивость).`
            });

            // Наносим половину урона хранителю
            await MidiQOL.applyTokenDamage(
                [{ damage: halfDamage, type: workflow.defaultDamageType }],
                halfDamage,
                new Set([guardianToken]),
                workflow.item?.uuid,
                new Set()
            );
            console.log(`${PREFIX} Хранителю ${guardianActor.name} нанесён урон ${halfDamage}`);

            // Реакция одна — выходим
            break;
        }

        console.log(`${PREFIX} Оставшиеся цели после обработки:`, Array.from(workflow.targets).map(t => t.name));
    });
}


if(0){

    // =====================================================
    // Снаряд хаоса (Chaos Bolt) — тихая версия, только логи
    // =====================================================

    (async () => {
        const log = (...msg) => console.log("[ChaosBolt]", ...msg);

        let _isDouble = (args)=>{
            return args?.[0].damageRolls[0].dice[0].results[0].result === args?.[0].damageRolls[0].dice[0].results[1].result
        }

        log("=== НАЧАЛО ===");

        // 1. Получаем выбранную цель
        const targets = Array.from(game.user.targets);
        if (targets.length === 0) {
            log("Нет выбранной цели, выходим");
            return;
        }
        const targetToken = targets[0];
        const targetActor = targetToken.actor;
        if (!targetActor) {
            log("У цели нет актёра");
            return;
        }
        log("Цель:", targetToken.name, args?.[0].damageRolls);

        // 2. Бросок урона 2d8+1d6
        const roll = await new Roll("2d8 + 1d6").evaluate();
        //await roll.toMessage({ flavor: "Снаряд хаоса — урон" });
        const totalDamage = roll.total;
        log("Бросок урона:", roll.formula, "=", totalDamage);

        // 3. Определяем тип урона по первому d8
        let d8values = [];
        for (let term of roll.terms) {
            if (term instanceof Die && term.faces === 8) {
                d8values.push(...term.results.map(r => r.result));
                if (d8values.length >= 2) break;
            }
        }
        const d1 = d8values[0] || 1;
        const d2 = d8values[1] || 1;
        const isDouble = _isDouble(args);
        const typeMap = { 1: "acid", 2: "cold", 3: "fire", 4: "force", 5: "lightning", 6: "poison", 7: "psychic", 8: "thunder" };
        const damageType = typeMap[d1] || "force";
        log(`Тип урона: ${damageType}, дубль: ${isDouble}`);

        // 4. Наносим урон первой цели
        const hp = targetActor.system.attributes.hp;
        const newHp = Math.max(0, hp.value - totalDamage);
        //await targetActor.update({ "system.attributes.hp.value": newHp });
        log(`${targetToken.name}: ${hp.value} → ${newHp} (урон ${totalDamage} ${damageType})`);

        // 5. Если нет дубля — выходим
        if (!isDouble) {
            log("Нет дубля, завершаем");
            return;
        }

        // 6. Дубль — ищем вторую цель в радиусе 30 футов
        log("Дубль! Поиск второй цели...");
        const radiusPx = (30 / 5) * canvas.grid.size;
        const center = targetToken.center;
        const candidates = canvas.tokens.placeables.filter(t => {
            if (t.id === targetToken.id) return false;
            if (t.document.disposition>0) return false;
            if (!t.actor || t.actor.system.attributes.hp.value <= 0) return false;
            const dist = Math.hypot(t.center.x - center.x, t.center.y - center.y);
            return dist <= radiusPx;
        });
        log("Кандидаты:", candidates.map(t => t.name).join(", ") || "нет");

        if (candidates.length === 0) {
            log("Нет целей для перескока");
            return;
        }

        let secondTarget = candidates[0];
        if (candidates.length > 1) {
            const buttons = {};
            for (let t of candidates) buttons[t.id] = { label: t.name };
            buttons.cancel = { label: "Отмена" };
            const selectedId = await Dialog.wait({
                title: "Снаряд хаоса — перескок",
                content: `<p>Выпал дубль! Выберите вторую цель в пределах 30 футов от <strong>${targetToken.name}</strong>:</p>`,
                buttons: buttons
            });
            if (!selectedId || selectedId === "cancel") {
                log("Перескок отменён пользователем");
                return;
            }
            secondTarget = candidates.find(t => t.id === selectedId);
            if (!secondTarget) return;
        }
        log("Вторая цель:", secondTarget.name);

        // 7. Бросок урона для второй цели
        const roll2 = await new Roll("2d8 + 1d6").evaluate();
        await roll2.toMessage({ flavor: "Снаряд хаоса — урон по второй цели" });
        const totalDamage2 = roll2.total;
        log("Урон по второй цели:", totalDamage2);

        const hp2 = secondTarget.actor.system.attributes.hp;
        const newHp2 = Math.max(0, hp2.value - totalDamage2);
        await secondTarget.actor.update({ "system.attributes.hp.value": newHp2 });
        log(`${secondTarget.name}: ${hp2.value} → ${newHp2} (урон ${totalDamage2})`);

        log("=== ЗАВЕРШЕНО ===");
    })();

}