/**
 * Получение задания
 * @param data информация о текущем положении, о союзниках, о врагах, доступных действиях
 */
export function getAction(data) {

    console.log('getAction', data);
    let prompt  = `Ты персонаж компьютерной игры. 
    тебе доступны следующие действия 
    move 
    у тебя есть Х move которые ты можешь сделать по направлениям left/down/right/left
    
    способности
    у тебя есть способности [Короткий меч][Короткий лук]
    
    союзники
    Твои союзники [список союзников в кородинатах]
    
    враги
    Твои враги [список врагов]
    
    информация о персонаже
    Ты находишься по координатам
    
    Твой ответ должен быть в следующем формате
    [тип_действия шаг,способность,цель]/[действие]
    
    Пример
    move/left
    move/left
    move/left
    Цель/враг_3
    Способность/Короткий меч
    move/right
    move/right
    
    
    Пример 2 
    Цель/враг_3
    Способность/Короткий лук
    move/up
    move/up
    move/right
    move/right
    move/right
    `;

    0 && fetch('http://localhost:9999/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        body: JSON.stringify({ text: 'ты кобольд?' })
    }).then(r => r.json()).then(console.log);
    return [{action:'move',conf:{direction:'up'}}];
}