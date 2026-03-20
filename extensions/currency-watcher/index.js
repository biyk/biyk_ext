
const limitCoinsTreasute = 1600;

// Функция для получения текущего баланса из данных сцены
async function getSceneCoins() {
    const sceneCoins = canvas.scene.getFlag("world", "totalCopper") || 0;
    return sceneCoins;
}

// Функция для обновления баланса в данных сцены
async function updateSceneCoins(newCopperValue) {
    await canvas.scene.setFlag("world", "totalCopper", newCopperValue);
}

// Функция для добавления монет актеру
async function addCoinsToActor(actor, coinType, amount) {
    if (!actor) return false;

    const currency = actor.system.currency;
    let updateData = {};

    switch(coinType) {
        case "cp": // Медные
            updateData["system.currency.cp"] = currency.cp + amount;
            break;
        case "sp": // Серебряные
            updateData["system.currency.sp"] = currency.sp + amount;
            break;
        case "gp": // Золотые
            updateData["system.currency.gp"] = currency.gp + amount;
            break;
        default:
            console.error("Неизвестный тип монеты:", coinType);
            return false;
    }

    try {
        await actor.update(updateData);
        return true;
    } catch (error) {
        console.error("Ошибка при добавлении монет:", error);
        return false;
    }
}

// Основная функция обработки
async function handleCoinSearch(speaker, actor, token, character, tile, method, pt, args, scene, event) {
    // Логируем входные параметры для отладки
    console.log("Параметры:", {speaker, actor, token, character, tile, method, pt, args, scene, event});

    // Проверяем, что есть актер
    if (!actor) {
        console.error("Актер не найден!");
        return;
    }

    // Получаем текущий баланс из данных сцены
    const currentCopper = await getSceneCoins();

    // Проверяем, достигнут ли лимит (1600 медных = 16 золотых)
    if (currentCopper >= limitCoinsTreasute) {
        const limitMessage = `${actor.name}: Скорее всего тут больше ничего нет.`;
        ChatMessage.create({
            content: limitMessage,
            speaker: speaker
        });
        return;
    }

    // Генерируем случайное число от 1 до 100
    const roll = Math.floor(Math.random() * 100) + 1;
    let message = "";
    let coinsAdded = false;
    let coinType = "";
    let coinAmount = 0;
    let copperValue = 0;

    // Определяем результат по шансам
    if (roll <= 50) { // 50% - 1 медная монета
        copperValue = 1;
        if (currentCopper + copperValue <= limitCoinsTreasute) {
            const added = await addCoinsToActor(actor, "cp", 1);
            if (added) {
                coinsAdded = true;
                coinType = "медную";
                coinAmount = 1;
                message = `${actor.name} нашел 1 медную монету!`;
            }
        }
    } else if (roll <= 60) { // 10% - 1 серебряная монета (50-60 = 10%)
        copperValue = 10; // 1 серебряная = 10 медных
        if (currentCopper + copperValue <= limitCoinsTreasute) {
            const added = await addCoinsToActor(actor, "sp", 1);
            if (added) {
                coinsAdded = true;
                coinType = "серебряную";
                coinAmount = 1;
                message = `${actor.name} нашел 1 серебряную монету!`;
            }
        }
    } else if (roll === 61) { // 1% - 1 золотая монета (ровно 61)
        copperValue = 100; // 1 золотая = 100 медных
        if (currentCopper + copperValue <= limitCoinsTreasute) {
            const added = await addCoinsToActor(actor, "gp", 1);
            if (added) {
                coinsAdded = true;
                coinType = "золотую";
                coinAmount = 1;
                message = `${actor.name} нашел 1 золотую монету! Удача!`;
            }
        }
    } else {
        // 39% - ничего не найдено (62-100)
        message = `${actor.name} ничего не нашел.`;
    }

    // Если монеты были добавлены, обновляем баланс сцены
    if (coinsAdded && copperValue > 0) {
        const newTotal = currentCopper + copperValue;
        await updateSceneCoins(newTotal);

        // Проверяем, достигнут ли лимит после добавления
        if (newTotal >= limitCoinsTreasute) {
            message += ` Скорее всего тут больше ничего нет.`;
        }
    }

    // Отправляем сообщение в чат
    if (message) {
        ChatMessage.create({
            content: message,
            speaker: speaker
        });
    }

    // Выводим информацию в консоль для отладки
    console.log(`Бросок: ${roll}, Найдено: ${coinsAdded ? coinAmount + " " + coinType + " монета" : "ничего"}, 
                 Текущий баланс сцены: ${await getSceneCoins()} медных монет`);
}

// Вызываем основную функцию
handleCoinSearch(speaker, actor, token, character, tile, method, pt, args, scene, event).catch(console.error);