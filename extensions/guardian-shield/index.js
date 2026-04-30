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
            const guardians = canvas.tokens.placeables.filter(t => {
                if (!t.actor) return false;
                if (t.actor.id === targetToken.actor.id) return false;

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