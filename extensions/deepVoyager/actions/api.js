/**
 * Формирование промпта для ИИ
 * @param data информация о текущем положении, о союзниках, о врагах, доступных действиях
 */
import {log} from "../utils/logger.js";
import {buildPrompt, buildPromptBoss} from "../utils/prompt.js";

// ВАЖНО: fetch к нейросети ДЛЯ ВСЕГДА оставляем, не удалять!
const AI_API_URL = 'http://localhost:9999/ask';

export async function getAction(data) {
    log.info('getAction', data);
    let prompt = '';
    if (data.disposition===-2){
        prompt = buildPromptBoss(data);
    } else {
        prompt = buildPrompt(data);
    }


    let response = await fetch(AI_API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        body: JSON.stringify({ text: prompt })
    }).then(r => r.json());
    
    log.info('AI Response:', response);
    let actions = parseResponse(response);
    log.info('Parsed actions:', actions);
    
    return actions.length ? actions : [];
}

/**
 * Парсинг ответа от нейросети
 * @param response текст ответа от ИИ (строка или объект с полем response/text/content/answer)
 * @returns массив действий [{action, conf}]
 */
function parseResponse(response) {
    if (!response) return [];
    
    let text = typeof response === 'string' ? response : (response.response || response.text || response.content || response.answer || "");
    if (!text) return [];
    
    const actions = [];
    
    // Ищем все команды через regex (action может быть в любой части строки)
    const regex = /(move|use|target|message)\/([^\n]+)$/gm;
    let match;
    
    while ((match = regex.exec(text)) !== null) {
        const action = match[1].trim().toLowerCase();
        const param = match[2].trim();
        
        if (action === 'move') {
            actions.push({action: 'move', conf: {direction: param}});
        } else if (action === 'use') {
            actions.push({action: 'use', conf: {itemId: param}});
        } else if (action === 'target') {
            actions.push({action: 'target', conf: {id: param}});
        } else if (action === 'message') {
            const msgParts = param.split('/');
            if (msgParts.length >= 2) {
                const language = msgParts[0].trim();
                const msgText = msgParts.slice(1).join('/').trim();
                if (language && msgText) {
                    actions.push({action: 'message', conf: {language, text: msgText}});
                }
            }
        }
    }
    
return actions;
}
