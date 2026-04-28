export function buildPrompt(data) {
    let disposition = { 1: "союзник", "-1": "враг", "0": "нейтральный" };

    let friendsList = data.friends.length
        ? data.friends.map(t => `${t.name} AC:${t.ac || "?"} статус:${t.status} экипировка:${t.weapon?.name || "нет"} позиция:(${t.x},${t.y}) id: ${t.id}`).join(", ")
        : "нет";

    let enemiesList = data.enemies.length
        ? data.enemies.map(t => `${t.name} AC:${t.ac || "?"} статус:${t.status} экипировка:${t.weapon?.name || "нет"} позиция:(${t.x},${t.y}) id: ${t.id}`).join(", ")
        : "нет";

    let neutralsList = data.neutrals.length
        ? data.neutrals.map(t => `${t.name}  AC:${t.ac || "?"} статус:${t.status} экипировка:${t.weapon?.name || "нет"} позиция:(${t.x},${t.y}) id: ${t.id}`).join(", ")
        : "нет";

    let actionsList = data.availableActions.map(a => {
        let info = `[${a.name}] тип:${a.type} id_оружия ${a.id}`;
        if (a.range && a.rangeAll) info += ` Дистанция:${a.rangeAll}фт уверенно (${a.range} фт с помехой)`;
        if (a.uses) info += ` заряды:${a.uses}/${a.maxUses}`;
        if (a.damage) info += ` урон:${a.damage}`;
        //if (a.description) info += ` Описание:${a.description}`;

        return info;
    }).join("\n");

    let featsList = data.availableFeats.map(a => {
        let info = `[${a.name}] активно:${a.enabled}`;


        return info;
    }).join("\n");


    let gmNotes = localStorage.getItem('gmNotes')|| '';
    let gmPrompt = (gmNotes)?`##ВАЖНО! ПРИКАЗ ОТ ГМ:
     ${gmNotes} `:'';

    let prompt = `Ты персонаж в D&D кампании: ${data.name} Ты сейчас в бою, Ты ${data.status} 
    Я игровая программа которая ждет от тебя ответа о твоих действиях в мире
    Используй все доступные тебе знания из D&D  о своих способностях и способностях врагов для достижения своих целей
    Ты можешь выбрать любое действие исходя из твоих интересов, как если бы ты был настоящим ${data.name}
    Ты владеешь языками ${data.languages}
Ты находишься на позиции (${data.x || 0},${data.y || 0}), размер клетки: ${data.step} px - это 5 футов, скорость: ${data.speed} футов за ход
у тебя есть движение  ${data.speed/5} шагов
также у тебя есть одно действие из списка Доступные действия

## Союзники (${data.friends.length})
${friendsList}

## Враги (${data.enemies.length})
${enemiesList}

## Нейтральные (${data.neutrals.length})
${neutralsList}

## Доступные действия
${actionsList}

## Текущие эффекты
${featsList}

## Общение
В качестве свободного действия ты можешь передать сообщение союзникам или врагам, одно за раз
message/draconic/Я кобольд!!!

## Формат ответа
Выведи последовательность действий, по одному на строке:
- move/направление - перемещение по прямой (up/down/left/right) по диагонали (upleft, upright, downleft,downright)
- use/имя_предмета - использовать предмет/заклинание
- target/id_цели - выбрать цель

Шаблон ответа (Отвечай ТОЛЬКО так):
move/up
move/upright
//я буду атаковать мечем
target/id_цели
//я атакую гоблина т.к. он мне не нравится
use/id_оружия
message/язык_сообщения/текст сообщения


    Пример 2 
    target/0pVt9lJTubIk7bBZ
    use/Hy3EM9cm9BsDvYHq
    message/draconic/Умри ничтожество!
    move/up
    move/up
    move/right
    move/upright
    move/upright
    //я хочу атаковать Стражника 0pVt9lJTubIk7bBZ из лука т.к. я далеко а у него копье
    
    Пример 3
    // Я на (3060,810), здоровый кобольд на (3060,2160). Разница y = 1350 (15 шагов). мне нужно увеличить свою координату y Враг южнее → иду down.
    move/down
    move/down
    move/down
    move/downleft
    move/down
    move/downleft
    message/common/За императора!

    // Теперь я на (3060,1350). До кобольда осталось 9 шагов (810 px). Атака пока невозможна.
    
    размышления начинай с символа решетка // 
    иначе твой ход будет проигнорирован и будет передан следующему персонажу

Движение рассчитывается по сетке. Учитывай позиции врагов и союзников.

##ВНИМАНИЕ
right - увеличить координату x на ${data.step}
left - уменьшить координату x на ${data.step}
up - уменьшает координату y на ${data.step}
down - увеличивает координату y на ${data.step}
upright - x+${data.step}, y-${data.step}
upleft - x-${data.step}, y-${data.step}
downright - x+${data.step}, y+${data.step}
downleft - x-${data.step}, y+${data.step}
все персонажи кроме мертвых являются препятствием через них пройти нельзя только обойти
нельзя зайти в ячейку в которой уже есть кто-то
${gmPrompt}

`;
//ВНИМАТЕЛЬНО смотри на ID которые отправляешь если будешь использовать неверный ID твое действие не сработает
    return prompt;
}

export function buildPromptBoss(data) {
    let disposition = { 1: "союзник", "-1": "враг", "0": "нейтральный" };

    let friendsList = data.friends.length
        ? data.friends.map(t => `${t.name} AC:${t.ac || "?"} статус:${t.status} экипировка:${t.weapon?.name || "нет"} позиция:(${t.x},${t.y}) id: ${t.id}`).join(", ")
        : "нет";

    let enemiesList = data.enemies.length
        ? data.enemies.map(t => `${t.name} AC:${t.ac || "?"} статус:${t.status} экипировка:${t.weapon?.name || "нет"} позиция:(${t.x},${t.y}) id: ${t.id}`).join(", ")
        : "нет";

    let neutralsList = data.neutrals.length
        ? data.neutrals.map(t => `${t.name}  AC:${t.ac || "?"} статус:${t.status} экипировка:${t.weapon?.name || "нет"} позиция:(${t.x},${t.y}) id: ${t.id}`).join(", ")
        : "нет";

    let actionsList = data.availableActions.map(a => {
        let info = `[${a.name}] тип:${a.type} id_оружия ${a.id}`;
        if (a.range && a.rangeAll) info += ` Дистанция:${a.rangeAll}фт уверенно (${a.range} фт с помехой)`;
        if (a.uses) info += ` заряды:${a.uses}/${a.maxUses}`;
        if (a.damage) info += ` урон:${a.damage}`;
        //if (a.description) info += ` Описание:${a.description}`;

        return info;
    }).join("\n");

    let featsList = data.availableFeats.map(a => {
        let info = `[${a.name}] активно:${a.enabled}`;


        return info;
    }).join("\n");


    let gmNotes = localStorage.getItem('gmNotes')|| '';
    let gmPrompt = (gmNotes)?`##ВАЖНО! ПРИКАЗ ОТ ГМ:
     ${gmNotes} `:'';

    let prompt = `Ты БОСС в D&D кампании: ${data.name} Ты сейчас в бою, Ты ${data.status} 
    Я игровая программа которая ждет от тебя ответа о твоих действиях в мире
    Используй все доступные тебе знания из D&D  о своих способностях и способностях врагов для достижения своих целей
    Ты можешь выбрать любое действие исходя из твоих интересов, как если бы ты был настоящим ${data.name}
    Ты владеешь языками ${data.languages}
    Ты находишься на позиции (${data.x || 0},${data.y || 0}), размер клетки: ${data.step} px - это 5 футов, скорость: ${data.speed} футов за ход
    у тебя есть движение  ${data.speed/5} шагов
    также у тебя есть одно действие из списка Доступные действия
    
    ## Союзники (${data.friends.length})
    ${friendsList}
    
    ## Враги (${data.enemies.length})
    ${enemiesList}
    
    ## Нейтральные (${data.neutrals.length})
    ${neutralsList}
    
    ## Доступные действия
    ${actionsList}
    
    ## Текущие эффекты
    ${featsList}
    
    ## Общение
    В качестве свободного действия ты можешь передать сообщение союзникам или врагам, одно за раз
    message/draconic/Я кобольд!!!
    
    ## Формат ответа
    Выведи последовательность действий, по одному на строке:
    - move/направление - к какой цели ты перемещаешься
    - use/имя_предмета - использовать предмет/заклинание
    - target/id_цели - выбрать цель
    
    Шаблон ответа (Отвечай ТОЛЬКО так):
    target/id_цели
    move/Гоблин
    //я буду атаковать мечем
    //я атакую гоблина т.к. он мне не нравится
    use/id_оружия
    message/язык_сообщения/текст сообщения


    Пример 2 
    target/0pVt9lJTubIk7bBZ
    move/Имя_цели
    use/Hy3EM9cm9BsDvYHq
    message/draconic/Умри ничтожество!
    //я хочу атаковать Стражника 0pVt9lJTubIk7bBZ из лука т.к. я далеко а у него копье
    
    Пример 3
    // Я на (3060,810), здоровый кобольд на (3060,2160). Я хочу убить Крысу
    target/0pVt9lJTubIk7bBZ
    move/Крыса
    message/common/За императора!

    // Теперь я на (3060,1350). До кобольда осталось 9 шагов (810 px). Атака пока невозможна.
    
    размышления начинай с символа решетка // 
    иначе твой ход будет проигнорирован и будет передан следующему персонажу

    Движение рассчитывается по сетке. Учитывай позиции врагов и союзников.

${gmPrompt}

`;
//ВНИМАТЕЛЬНО смотри на ID которые отправляешь если будешь использовать неверный ID твое действие не сработает
    return prompt;
}