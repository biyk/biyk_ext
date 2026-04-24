/**
 * Формирование промпта для ИИ
 * @param data информация о текущем положении, о союзниках, о врагах, доступных действиях
 */
function buildPrompt(data) {
    let disposition = { 1: "союзник", "-1": "враг", "0": "нейтральный" };
    
    let friendsList = data.friends.length 
        ? data.friends.map(t => `${t.name} AC:${t.ac || "?"} статус:${t.status} оружие:${t.weapon?.name || "нет"}(id_оружия: ${t.weapon?.id}) позиция:(${t.x},${t.y}) id: ${t.id}`).join(", ")
        : "нет";
    
    let enemiesList = data.enemies.length
        ? data.enemies.map(t => `${t.name} AC:${t.ac || "?"} статус:${t.status} оружие:${t.weapon?.name || "нет"}(id_оружия: ${t.weapon?.id}) позиция:(${t.x},${t.y}) id: ${t.id}`).join(", ")
        : "нет";

    let neutralsList = data.neutrals.length
        ? data.neutrals.map(t => `${t.name}  AC:${t.ac || "?"} статус:${t.status} оружие:${t.weapon?.name || "нет"}(id_оружия: ${t.weapon?.id}) позиция:(${t.x},${t.y}) id: ${t.id}`).join(", ")
        : "нет";

    let actionsList = data.availableActions.map(a => {
        let info = `[${a.name}] тип:${a.type} id_оружия ${a.id}`;
        if (a.range) info += ` Дистанция:${a.range} фт`;
        if (a.uses) info += ` заряды:${a.uses}/${a.maxUses}`;
        if (a.damage) info += ` урон:${a.damage}`;
        //if (a.description) info += ` Описание:${a.description}`;

        return info;
    }).join("\n");

    let prompt = `Ты персонаж в D&D кампании: ${data.name} Ты сейчас в бою, Ты ${data.status} 
    Я игровая программа которая ждет от тебя ответа о твоих действиях в мире
    Используй все доступные тебе знания о своих способностях и способностях врагов для достижения своих целей
    Ты можешь выбрать любое действие исходя из твоих интересов
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

## Формат ответа
Выведи последовательность действий, по одному на строке:
- move/направление - перемещение (up/down/left/right)
- use/имя_предмета - использовать предмет/заклинание
- target/имя_цели - выбрать цель

Шаблон ответа (Отвечай ТОЛЬКО так):
move/up
move/right
//я буду атаковать мечем
target/id_цели
//я атакую гоблина т.к. он мне не нравится
use/id_оружия


    Пример 2 
    target/0pVt9lJTubIk7bBZ
    use/Hy3EM9cm9BsDvYHq
    move/up
    move/up
    move/right
    move/right
    move/right
    //я хочу атаковать Стражника 0pVt9lJTubIk7bBZ из лука т.к. я далеко а у него копье
    
    Пример 3
    // Я на (3060,810), здоровый кобольд на (3060,2160). Разница y = 1350 (15 шагов). мне нужно увеличить свою координату y Враг южнее → иду down.
    move/down
    move/down
    move/down
    move/down
    move/down
    move/down
    // Теперь я на (3060,1350). До кобольда осталось 9 шагов (810 px). Атака пока невозможна.
    
    размышления начинай с символа решетка // 
    иначе твой ход будет проигнорирован и будет передан следующему персонажу

Движение рассчитывается по сетке. Учитывай позиции врагов и союзников.

##ВНИМАНИЕ
right - увеличить координату x на ${data.step}
left - уменьшить координату x на ${data.step}
up - уменьшает координату y на ${data.step}
down - увеличивает координату y на ${data.step}

`;

    return prompt;
}

// ВАЖНО: fetch к нейросети ДЛЯ ВСЕГДА оставляем, не удалять!
const AI_API_URL = 'http://localhost:9999/ask';

export async function getAction(data) {
    console.log('getAction', data);
    
    let prompt = buildPrompt(data);

    // ЗАПРОС К НЕЙРОСЕТИ - НЕ УДАЛЯТЬ!
    let response = await fetch(AI_API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        body: JSON.stringify({ text: prompt })
    }).then(r => r.json());
    
    console.log('AI Response:', response);
    let actions = parseResponse(response);
    console.log('Parsed actions:', actions);
    
    return actions.length ? actions : [];
}

/**
 * Парсинг ответа от нейросети
 * @param response текст ответа от ИИ (строка или объект с полем response/text/content/answer)
 * @returns массив действий [{action, conf}]
 */
function parseResponse(response) {
    if (!response) return [];
    
    // Поддерживаем строку или объект {response: "...", text: "...", content: "...", answer: "..."}
    let text = typeof response === 'string' ? response : (response.response || response.text || response.content || response.answer || "");
    if (!text) return [];
    
    const actions = [];
    const lines = text.split('\n');
    
    for (const line of lines) {
        // Очистка: убираем комментарии (всё после //) и пустые строки
        let cleaned = line.split('//')[0].trim();
        if (!cleaned) continue;
        
        // Парсим формат action/param
        let parts = cleaned.split('/');
        if (parts.length < 2) continue;
        
        let action = parts[0].trim().toLowerCase();
        let param = parts[1].trim();
        
        if (action === 'move') {
            if (['up','down','left','right'].includes(param)) {
                actions.push({action: 'move', conf: {direction: param}});
            }
        } else if (action === 'use') {
            actions.push({action: 'use', conf: {itemId: param}});
        } else if (action === 'target') {
            actions.push({action: 'target', conf: {id: param}});
        }
    }
    
    return actions;
}
