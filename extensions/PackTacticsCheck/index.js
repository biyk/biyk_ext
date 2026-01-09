export function init() {
    console.log("Pack Tactics Script | Инициализация");

    // ============================================
    // 1. ГЛАВНАЯ ФУНКЦИЯ ПРОВЕРКИ ТАКТИКИ СТАИ
    // ============================================
    async function checkPackTacticsForToken(token) {
        if (!token?.actor) {
            console.log("Pack Tactics | Токен не найден");
            return;
        }

        const actor = token.actor;
        console.log(`Pack Tactics | Проверка для ${actor.name}`);

        // A) Проверяем наличие способности "Тактика стаи"
        const hasPackTactics = checkPackTacticsAbility(actor);
        if (!hasPackTactics) {
            console.log("Pack Tactics | У актёра нет способности");
            return;
        }

        // B) Проверяем, есть ли уже эффект
        const existingEffect = findPackTacticsEffect(actor);


        // C) Проверяем наличие союзников в радиусе 5 футов
        const hasNearbyAllies = checkNearbyAllies(token);

        // D) Если есть союзники - создаём эффект
        if (hasNearbyAllies) {
            if (existingEffect) {
                console.log("Pack Tactics | Эффект уже активен",);
                return;
            }
            await createPackTacticsEffect(actor, token);
        } else {
            const existingEffect = findPackTacticsEffect(actor);
            await existingEffect.delete();
            console.log("Pack Tactics | Нет союзников рядом, эффект не активирован");
        }
    }

    // ============================================
    // 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
    // ============================================

    // Проверка наличия способности "Тактика стаи"
    function checkPackTacticsAbility(actor) {
        let allEffects = [
            ...actor.effects.contents,
            ...actor.items.reduce((acc, i) => acc.concat(i.effects.contents), [])
        ];
        // Способ 1: Поиск в списке черт/способностей
        if (allEffects.length) {
            const packTacticsItem = allEffects.find(item =>
                item.name?.toLowerCase().includes("тактик") &&
                item.name?.toLowerCase().includes("стаи")
            );
            if (packTacticsItem) return true;
        }

        // Добавьте другие способы проверки по необходимости
        console.log("Pack Tactics | Способность не найдена в стандартных местах");
        return false;
    }

    // Поиск существующего эффекта Тактики стаи
    function findPackTacticsEffect(actor) {
        if (!actor.effects) return null;

        return actor.effects.find(effect =>
            effect?.name?.toLowerCase().includes("тактик") ||
            effect?.name?.toLowerCase().includes("pack tactic") ||
            effect?.flags?.dae?.specialDuration?.includes("turnEnd")
        );
    }

    // Проверка наличия союзников в радиусе 5 футов
    function checkNearbyAllies(token) {
        const gridSize = canvas.grid.size;
        const range = 5; // 5 футов

        let nearbyTokens = canvas.tokens.placeables.filter(t => {
            // Пропускаем самого себя
            if (t.id === token.id) return false;

            // Проверяем, что токен живой и имеет актёра
            if (!t.actor || t.actor.system?.attributes?.hp?.value <= 0) return false;

            // Проверяем отношение (союзник/враг)
            let isAlly = t.document.disposition === token.document.disposition;
            if (!isAlly) return false;

            // Проверяем расстояние
            let distance = canvas.grid.measureDistance(token, t);
            return distance <= 10;
        });

        console.log(`Pack Tactics | Найдено союзников: ${nearbyTokens.length}`);
        return nearbyTokens.length > 0;
    }

    // Создание эффекта Тактики стаи
    async function createPackTacticsEffect(actor, token) {
        console.log(`Pack Tactics | Создаём эффект для ${actor.name}`);

        const effectData = {
            name: "Тактика стаи (Pack Tactics)",
            icon: "icons/creatures/abilities/paw-print-orange.webp", // Замените на свою иконку
            origin: actor.uuid,
            disabled: false,
            duration: {
                rounds: 1,
                startRound: game.combat?.round,
                startTurn: game.combat?.turn,
                seconds: 6
            },
            changes: [
                // Способ 1: Для Midi-QoL
                {
                    key: "flags.midi-qol.advantage.attack.all",
                    mode: CONST.ACTIVE_EFFECT_MODES.OVERRIDE,
                    value: true,
                    priority: 20
                },
                // Способ 2: Для базовой системы D&D5e
                {
                    key: "flags.dnd5e.advantage.attack.all",
                    mode: CONST.ACTIVE_EFFECT_MODES.OVERRIDE,
                    value: true,
                    priority: 10
                }
            ],
            flags: {
                core: {
                    statusId: "packTactics"
                },
                dae: {
                    specialDuration: ["turnEnd"],
                    stackable: false,
                    transfer: false
                }
            }
        };

        try {
            // Удаляем старые эффекты Тактики стаи (на всякий случай)
            const oldEffects = actor.effects.filter(e =>
                e.name?.includes("Тактика стаи") || e.name?.includes("Pack Tactics")
            );
            for (const effect of oldEffects) {
                await effect.delete();
            }

            // Создаём новый эффект
            await actor.createEmbeddedDocuments("ActiveEffect", [effectData]);

            // Визуальная индикация
            if (token?.isVisible) {
                // Мигание токена
                token.animate({
                    attribute: "alpha",
                    to: 0.5,
                    duration: 200
                }).then(() => {
                    token.animate({
                        attribute: "alpha",
                        to: 1.0,
                        duration: 200
                    });
                });

                // Показываем текст
                if (CONFIG.Canvas?.animation?.occludedPulse) {
                    const text = new PreciseText("Тактика стаи!", {
                        fontSize: 24,
                        fill: 0x00FF00,
                        stroke: 0x000000,
                        strokeThickness: 4
                    });
                    canvas.interface.addChild(text);
                    text.position.set(token.center.x, token.center.y - 50);

                    setTimeout(() => canvas.interface.removeChild(text), 2000);
                }
            }

            console.log("Pack Tactics | Эффект успешно создан!");
        } catch (error) {
            console.error("Pack Tactics | Ошибка создания эффекта:", error);
        }
    }

    // ============================================
    // 3. ХУКИ ДЛЯ АВТОМАТИЧЕСКОГО ВЫЗОВА
    // ============================================

    // Хук: Начало хода в комбате
    Hooks.on("combatTurn", async (combat, combatant) => {
        if (!combatant?.token) return;

        console.log(`Pack Tactics | Начало хода ${combatant.name}`);

        const token = canvas.tokens.get(combatant.token.id);
        if (!token) return;

        // Небольшая задержка для гарантии загрузки всех данных
        setTimeout(() => checkPackTacticsForToken(token), 100);
    });

    // Хук: После перемещения токена
    Hooks.on("updateToken", async (tokenData, updateData, options, userId) => {
        // Проверяем, что это перемещение (изменились координаты)
        console.info(tokenData, updateData, options, userId);
        const positionChanged = updateData.x !== undefined || updateData.y !== undefined;
        if (!positionChanged) return console.log('Токен не двигался');

        // Проверяем, что это наш пользователь (чтобы не срабатывало многократно)
        if (userId !== game.userId && !game.user.isGM) return console.log('Запрет на использование');

        console.log("Pack Tactics | Токен перемещён");

        // Находим токен на канвасе
        const token = canvas.tokens.get(tokenData._id);
        if (!token) return;

        // Небольшая задержка для стабилизации
        setTimeout(() => checkPackTacticsForToken(token), 300);
    });

    // Хук: Конец хода (удаляем эффект если нет союзников)
    Hooks.on("combatTurnEnd", async (combat, combatant) => {
        if (!combatant?.token) return;

        const token = canvas.tokens.get(combatant.token.id);
        if (!token?.actor) return;

        // Проверяем наличие эффекта
        const effect = findPackTacticsEffect(token.actor);
        if (!effect) return;

        // Проверяем, остались ли союзники
        const hasAllies = checkNearbyAllies(token);

        // Если союзников нет - удаляем эффект
        if (!hasAllies) {
            console.log(`Pack Tactics | У ${token.actor.name} больше нет союзников, удаляем эффект`);
            await effect.delete();
        }
    });

    console.log("Pack Tactics Script | Хуки зарегистрированы");
}