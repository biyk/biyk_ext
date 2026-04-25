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
        rangeAll: item.system.range?.value || 5,
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