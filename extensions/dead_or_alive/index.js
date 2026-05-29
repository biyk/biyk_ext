// ============================================================
// Стойкость нежити + Обработка смерти игрока
// Хук: dnd5e.preApplyDamage
// ============================================================

export function init() {
    Hooks.on("dnd5e.preApplyDamage", async (...args) => {
        // ---- БЛОК 1: Извлечение данных с логированием ----
        console.log("[UndeadFortitude] ===== ХУК dnd5e.preApplyDamage ВЫЗВАН =====");
        console.log("[UndeadFortitude] Получены аргументы:", args);

        // Пытаемся извлечь actor, damage, damageType, workflow
        let actor, damageAmount, damageType, isCritical, workflow;
        try {
            // Пример сигнатуры: (actor, damage, { type, isCritical, ... })
            if (args.length >= 2) {
                actor = args[0];
                damageAmount = args[1];
                const options = args[2] || {};
                damageType = options.type;
                isCritical = options.isCritical;
                workflow = options.workflow;
            }
            // Если сигнатура другая, попробуем адаптироваться (запасной вариант)
            if (!actor && args[0]?.actor) {
                actor = args[0].actor;
                damageAmount = args[0].damage;
                damageType = args[0].damageType;
                isCritical = args[0].isCritical;
                workflow = args[0];
            }
            console.log(`[UndeadFortitude] Интерпретировано: actor=${actor?.name}, damage=${damageAmount}, type=${damageType}, critical=${isCritical}`);
        } catch (err) {
            console.error("[UndeadFortitude] Ошибка извлечения аргументов хука:", err);
            return;
        }

        if (!actor || damageAmount === undefined) {
            console.warn("[UndeadFortitude] Не удалось получить actor или damage, хук прерван.");
            return;
        }

        // ------------------------------------------------------------
        // БЛОК A: Стойкость нежити (работает только для нежити)
        // ------------------------------------------------------------
        try {
            console.log("[UndeadFortitude] БЛОК A: начало проверки Стойкости нежити");

            const isUndead = actor.system.details?.type?.value?.toLowerCase().includes("undead")
                || actor.name.toLowerCase().includes("зомби")
                || actor.items.some(i => i.name.toLowerCase().includes("стойкость нежити"));
            if (!isUndead) {
                console.log("[UndeadFortitude] Существо не нежить, блок A пропущен.");
            } else {
                // Текущее HP после применения урона ещё не изменилось (preApplyDamage)
                const currentHp = actor.system.attributes.hp.value;
                const willBeZeroOrLess = (currentHp - damageAmount) <= 0;
                console.log(`[UndeadFortitude] Текущие HP=${currentHp}, урон=${damageAmount}, станет <=0? ${willBeZeroOrLess}`);

                if (willBeZeroOrLess) {
                    // Исключения
                    const isRadiant = damageType === "radiant";
                    if (isRadiant || isCritical) {
                        console.log(`[UndeadFortitude] Исключение: ${isRadiant ? "лучистый урон" : "критический удар"} – стойкость не сработает.`);
                        // Ничего не делаем, смерть наступит штатно
                    } else {
                        const dc = 5 + damageAmount;
                        console.log(`[UndeadFortitude] Спасбросок Выносливости СЛ=${dc}`);
                        const saveRoll = await actor.rollAbilitySave("con", { chatMessage: false });
                        const saveTotal = saveRoll.total;
                        console.log(`[UndeadFortitude] Результат спасброска: ${saveTotal}`);

                        if (saveTotal >= dc) {
                            // Успех: отменяем урон и устанавливаем 1 HP
                            console.log("[UndeadFortitude] Спасбросок успешен – отменяем урон, оставляем 1 HP");
                            // Отменяем применение урона (это preApplyDamage, можем вернуть false или изменить damage)
                            // Способ отмены: возвращаем false или меняем damage на 0
                            // Предположим, возврат false отменяет применение урона.
                            // Но так как мы в хуке, мы не можем прервать цепочку? Лучше изменить damage на 0.
                            // В данном хуке мы можем изменить второй аргумент (damage) если передать его по ссылке? Нет.
                            // Вместо этого мы вручную установим HP = 1 и вернём false, чтобы урон не применялся.
                            await actor.update({ "system.attributes.hp.value": 1 });
                            await ChatMessage.create({
                                content: `<strong>${actor.name}</strong> проявляет <strong>Стойкость нежити</strong> и остаётся с 1 ПЗ!<br>🎲 Спасбросок Выносливости: ${saveTotal} (СЛ ${dc})`,
                                speaker: ChatMessage.getSpeaker({ actor })
                            });
                            console.log("[UndeadFortitude] Урон отменён, HP=1.");
                            // Возвращаем false, чтобы предотвратить дальнейшее применение урона
                            return false;
                        } else {
                            console.log("[UndeadFortitude] Спасбросок провален – существо погибнет.");
                            await ChatMessage.create({
                                content: `<strong>${actor.name}</strong> не удаётся противостоять смерти – Стойкость нежити не помогает.<br>🎲 Спасбросок Выносливости: ${saveTotal} (СЛ ${dc})`,
                                speaker: ChatMessage.getSpeaker({ actor })
                            });
                            // Позволяем урону пройти
                        }
                    }
                } else {
                    console.log("[UndeadFortitude] HP не упадёт до 0, стойкость не нужна.");
                }
            }
        } catch (err) {
            console.error("[UndeadFortitude] ОШИБКА в блоке Стойкости нежити:", err);
            // Не прерываем выполнение, чтобы второй блок мог сработать
        }

        // ------------------------------------------------------------
        // БЛОК B: Обработка смерти игрока (телепорт, воскрешение, маркер)
        // ------------------------------------------------------------
        try {
            console.log("[DeathHandler] БЛОК B: обработка смерти игрока");

            const DEATH_MARKER_ACTOR_ID = "5pNGL93cGjOtmjkU";
            const RESPAWN_X = 1656;
            const RESPAWN_Y = 3528;

            const isPlayerActor = actor.type === "character" || actor.hasPlayerOwner;
            if (!isPlayerActor) {
                console.log("[DeathHandler] Не игровой персонаж, пропускаем.");
            } else if (canvas.scene.id !== 'ocnaVUdPmSkjKizF') {
                console.log(`[DeathHandler] Сцена ${canvas.scene.id} не целевая, пропускаем.`);
            } else {
                const currentHp = actor.system.attributes.hp.value;
                const willBeZeroOrLess = (currentHp - damageAmount) <= 0;
                if (!willBeZeroOrLess) {
                    console.log("[DeathHandler] Урон не убивает, пропускаем.");
                } else {
                    // Флаг двукратной обработки
                    const deathFlag = await actor.getFlag("world", "playerDeathProcessed");
                    if (deathFlag) {
                        console.log("[DeathHandler] Смерть уже обработана, пропускаем.");
                    } else {
                        await actor.setFlag("world", "playerDeathProcessed", true);
                        setTimeout(() => actor.unsetFlag("world", "playerDeathProcessed"), 2000);

                        const token = canvas.tokens.placeables.find(t => t.actor?.id === actor.id);
                        if (!token) {
                            console.log(`[DeathHandler] Токен для ${actor.name} не найден.`);
                        } else {
                            const deathX = token.x;
                            const deathY = token.y;
                            console.log(`[DeathHandler] Смерть в (${deathX}, ${deathY})`);

                            // Телепорт
                            await token.document.update({ x: RESPAWN_X, y: RESPAWN_Y }, { animate: false, teleport: true });
                            console.log(`[DeathHandler] Токен телепортирован на (${RESPAWN_X}, ${RESPAWN_Y})`);

                            // Полное восстановление HP
                            const maxHp = actor.system.attributes.hp.max;
                            await actor.update({ "system.attributes.hp.value": maxHp });
                            console.log(`[DeathHandler] HP восстановлено до ${maxHp}`);

                            // Создание маркера смерти
                            const markerActor = game.actors.get(DEATH_MARKER_ACTOR_ID);
                            if (!markerActor) {
                                console.warn(`[DeathHandler] Маркер с ID ${DEATH_MARKER_ACTOR_ID} не найден.`);
                            } else {
                                // Берём прототип токена из актёра-скелета
                                let tokenProto = markerActor.prototypeToken;
                                if (!tokenProto) {
                                    console.warn("[DeathHandler] У актёра-маркера нет prototypeToken, создаём минимальный.");
                                    tokenProto = {
                                        width: token.document.width,
                                        height: token.document.height,
                                        img: markerActor.img
                                    };
                                }
                                const markerTokenData = foundry.utils.mergeObject(foundry.utils.duplicate(tokenProto), {
                                    x: deathX,
                                    y: deathY,
                                    actorId: markerActor.id,
                                    name: markerActor.name,
                                    actorLink: false   // чтобы токен был независимой копией
                                });

                                const created = await canvas.scene.createEmbeddedDocuments("Token", [markerTokenData]);
                                if (created.length) {
                                    console.log(`[DeathHandler] Маркер "${markerActor.name}" создан.`);
                                } else {
                                    console.warn("[DeathHandler] Не удалось создать маркер.");
                                }
                            }
                        }
                    }
                }
            }
        } catch (err) {
            console.error("[DeathHandler] ОШИБКА в блоке обработки смерти игрока:", err);
        }

        console.log("[UndeadFortitude] ===== ЗАВЕРШЕНИЕ ХУКА =====");
        // Если ни один блок не вернул false, урон будет применён штатно
    });
}