export function getStatus(actor) {
    const hp = actor?.system?.attributes?.hp;
    const hpValue = hp?.value ?? 0;
    const hpMax = hp?.max ?? 1;
    const hpPercent = hpMax > 0 ? (hpValue / hpMax) * 100 : 0;

    if (hpValue === 0) return "мертв";
    if (hpPercent < 33) return "тяжело ранен";
    if (hpPercent < 66) return "ранен";
    return "здоров";
}

export function buildItemAction(item) {
    const description = item.system.description?.value
        ?.replace(/<[^>]+>/g, "")
        ?.replace(/@Compendium\[[^\]]+\]\{[^}]+\}/g, "")
        ?.replace(/\[\/[^\]]+\]/g, "")
        ?.replace(/[\n\r]+/g, " ")
        ?.trim()
        ?.substring(0, 200) || "";

    const action = {
        id: item.id,
        name: item.name,
        type: item.type,
        uses: item.system.uses?.value || null,
        maxUses: item.system.uses?.max || null,
        recharge: item.system.recharge?.value || null,
        range: item.system.range?.long || 5,
        rangeAll: item.system.range?.value || null,
        damage: item.system.damage?.parts?.[0]?.[0] || null,
        description: description
    };

    if (item.type === "weapon") {
        action.attackBonus = item.system.attackBonus || 0;
        action.properties = item.system.properties || {};
    }

    if (item.type === "spell") {
        action.level = item.system.level || 0;
        action.school = item.system.school || "";
    }

    return action;
}

/**
 * Вычисляет коэффициент схожести двух строк (0..1)
 * Использует расстояние Левенштейна + нормализацию регистра
 * @param {string} realId - настоящий ID (эталон)
 * @param {string} maybeId - проверяемый ID (от нейросети)
 * @param {boolean} caseSensitive - учитывать регистр? (по умолчанию false)
 * @returns {number} 1 - полностью совпадают, 0 - совершенно разные
 */
export function similarity(realId, maybeId, caseSensitive = false) {
    if (!realId || !maybeId) return 0;
    let a = caseSensitive ? realId : realId.toLowerCase();
    let b = caseSensitive ? maybeId : maybeId.toLowerCase();
    if (a === b) return 1;

    // Расстояние Левенштейна (динамическое программирование)
    const lenA = a.length;
    const lenB = b.length;
    // Матрица размером (lenA+1) x (lenB+1)
    let dp = Array(lenA + 1);
    for (let i = 0; i <= lenA; i++) dp[i] = Array(lenB + 1);
    for (let i = 0; i <= lenA; i++) dp[i][0] = i;
    for (let j = 0; j <= lenB; j++) dp[0][j] = j;
    for (let i = 1; i <= lenA; i++) {
        for (let j = 1; j <= lenB; j++) {
            const cost = a[i-1] === b[j-1] ? 0 : 1;
            dp[i][j] = Math.min(
                dp[i-1][j] + 1,      // удаление
                dp[i][j-1] + 1,      // вставка
                dp[i-1][j-1] + cost  // замена
            );
        }
    }
    const distance = dp[lenA][lenB];
    // Нормализуем: чем больше расстояние, тем меньше похожесть
    const maxLen = Math.max(lenA, lenB);
    if (maxLen === 0) return 0;
    return 1 - distance / maxLen;
}