export function init() {
    // Подписываемся на хук применения урона в Midi-QOL



    Hooks.on("createActiveEffect", async (ActiveEffect5e, config,uuid) => {
        if (ActiveEffect5e.name!=='Invisible') return;
        let actor = ActiveEffect5e.parent;
        const roll = new Roll("1d20");
        await roll.evaluate({async: true});
        // Получаем модификатор ловкости
        const dexMod = actor.system.abilities?.dex?.mod;
        if (dexMod === undefined) return;
        ActiveEffect5e.dc = roll.total + dexMod;
    })

    Hooks.on("midi-qol.postDamageRollComplete", async (workflow) => {
        try {
            // Проверяем, что у нас есть данные об атакующем и урон был нанесен
            console.log(workflow)
            if (!workflow.actor || !workflow.token) {
                return;
            }

            // Получаем актера-атакующего
            const attacker = workflow.actor;
            const attackerToken = workflow.token;

            console.log(`Проверка невидимости для ${attacker.name} после нанесения урона`);

            // Ищем эффект Invisible у атакующего
            // Проверяем различные возможные названия эффекта
            const invisibleEffects = attacker.effects.filter(effect => {
                const name = effect.label?.toLowerCase() || effect.name?.toLowerCase() || "";
                return name.includes("invisible") ||
                    name.includes("невидим") ||
                    effect.flags?.core?.statusId === "invisible";
            });

            // Если эффектов невидимости нет, выходим
            if (invisibleEffects.length === 0) {
                return;
            }

            console.log(`Найдено ${invisibleEffects.length} эффектов невидимости у ${attacker.name}`);

            // Удаляем все эффекты невидимости
            const effectIds = invisibleEffects.map(e => e.id);

            try {
                // Удаляем через deleteEmbeddedDocuments для сохранения в истории
                await attacker.deleteEmbeddedDocuments("ActiveEffect", effectIds);

                console.log(`Эффекты невидимости удалены у ${attacker.name}`);

                // Отправляем сообщение в чат (опционально)
                ChatMessage.create({
                    speaker: ChatMessage.getSpeaker({ token: attackerToken }),
                    content: `${attacker.name} теряет невидимость после атаки!`,
                    whisper: ChatMessage.getWhisperRecipients("GM")
                });

            } catch (error) {
                console.error("Ошибка при удалении эффектов невидимости:", error);
            }

        } catch (error) {
            console.error("Ошибка в хуке удаления Invisible:", error);
        }
    });

    // Хук: После перемещения токена
    Hooks.on("updateToken", async (tokenData, updateData, options, userId) => {
        // Проверяем, что это перемещение (изменились координаты)
        //console.info(tokenData, updateData, options, userId);
        const positionChanged = updateData.x !== undefined || updateData.y !== undefined;
        if (!positionChanged) return;// console.log('Токен не двигался');

        // Проверяем, что это наш пользователь (чтобы не срабатывало многократно)
        if (userId !== game.userId && !game.user.isGM) return console.log('Запрет на использование');

        // смотрим всех актеров и ищем среди них тех что с невидимостью ActiveEffect5e.name==='Invisible'
        // считаем до них расстояние если его видно и он в радиусе 30 футов
        // и если пассивная внимательность больше ActiveEffect5e.dc
        // выводим в консоль список актеров с невидимостью
    });

}