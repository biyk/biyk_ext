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
 * Вооружение токена для сервера /plan (поле payload["weapons"]).
 * Уверенная дистанция = range.value (для ближнего боя 5 футов, 10 — если есть
 * досягаемость), сомнительная = range.long (у ближнего боя совпадает с уверенной).
 * ranged — дальнобойное: выстрел в упор сервер считает сомнительным.
 * properties — коды свойств dnd5e (thr/rch/fin/…); метательное (thr) в упор бьёт уверенно.
 * @param {Token} token
 * @returns {Array<{id,name,damage,attackBonus,sureFt,doubtFt,ranged,properties}>}
 */
export function buildWeapons(token) {
    const weapons = [];
    for (let item of token?.actor?.items ?? []) {
        if (!isWeaponAttack(item)) continue;
        weapons.push(weaponEntry(item));
    }
    return weapons;
}

/**
 * Можно ли этим предметом атаковать как оружием? Тип `weapon` берём всегда,
 * остальное — если система помечает его как атаку оружием (actionType mwak/rwak):
 * так попадают природное оружие NPC (укус/когти), которое в dnd5e 3.x оформлено как feat.
 * @param {Item} item
 * @returns {boolean}
 */
function isWeaponAttack(item) {
    if (item.system.equipped === false) return false;   // не в руках — не бьём (у feats этого поля нет)
    if (item.type === 'weapon') return true;
    return ['mwak', 'rwak'].includes(item.system.actionType ?? item.system.attackType);
}

function weaponEntry(item) {
    const range = (typeof item.system.range === 'object' && item.system.range) || {};
    const sure = Math.max(Number(range.value) || 0, reachFt(item));
    const doubt = Math.max(Number(range.long) || 0, sure);
    return {
        id: item.id,
        name: item.name,
        damage: resolvedDamage(item),
        attackBonus: attackBonus(item),
        sureFt: sure,
        doubtFt: doubt,
        ranged: isRanged(item),
        properties: propertyList(item),
    };
}

/** Свойства предмета-оружия списком кодов: в 3.x это Set, в 2.x — объект {код: true}. */
function propertyList(item) {
    const properties = item.system.properties;
    if (properties instanceof Set) return [...properties];
    if (Array.isArray(properties)) return properties.filter(Boolean);
    if (properties && typeof properties === 'object') {
        return Object.keys(properties).filter(key => properties[key]);
    }
    return [];
}

/**
 * Дальнобойное ли: тип атаки системы (rwak), фолбэк — ненулевая дальность.
 * Метательное (свойство thr) не считается: бросок в упор идёт без помехи.
 */
function isRanged(item) {
    if (propertyList(item).includes('thr')) return false;
    const at = item.system.actionType ?? item.system.attackType;
    if (at) return at === 'rwak';
    const range = item.system.range || {};
    return (Number(range.value) || 0) > 5 || (Number(range.long) || 0) > 0;
}

/**
 * Бонус атаки: labels.toHit форматируется с пробелом («+ 4»), поэтому parseInt
 * давал NaN и бонус обнулялся — вытаскиваем знак с цифрами регуляркой.
 * Цепочка: labels.toHit → labels.modifier → магический бонус.
 */
function attackBonus(item) {
    const fromLabel = signedNumber(item.labels?.toHit) ?? signedNumber(item.labels?.modifier);
    if (fromLabel !== null) return fromLabel;
    return Number(item.system?.magicalBonus ?? item.system?.magicBonus ?? 0) || 0;
}

/** Число со знаком из произвольной строки («+ 4» → 4, «−2» → -2), иначе null. */
function signedNumber(text) {
    const m = /(−|-)?\s*\d+/.exec(String(text ?? ''));
    if (!m) return null;
    const value = Number(m[0].replace('−', '-').replace(/\s+/g, ''));
    return Number.isFinite(value) ? value : null;
}

/**
 * Разрешённый урон: в labels.derivedDamage[0].formula модификатор уже подставлен
 * («1d4 + 2»); пробелы убираем к тренировочному формату «1d4+2». Если labels не
 * вычисляются или формула осталась с @mod — фолбэк на сырую формулу системы.
 */
function resolvedDamage(item) {
    const derived = item.labels?.derivedDamage?.[0]?.formula;
    if (derived && !String(derived).includes('@')) return String(derived).replace(/\s+/g, '');
    return item.system.damage?.parts?.[0]?.[0] || null;
}

/** Средний урон по формуле «NdS±C»; null — если формула не читается. */
function damageAvg(formula) {
    const m = /(\d+)d(\d+)([+-]\d+)?/.exec(String(formula || '').replace(/\s+/g, ''));
    if (!m) return null;
    return (Number(m[1]) * (Number(m[2]) + 1)) / 2 + (Number(m[3]) || 0);
}

/** Досягаемость ближнего боя в футах: 5 без свойства reach, иначе 10. */
function reachFt(item) {
    if (propertyList(item).includes('rch')) return 10;
    const explicit = Number(item.reach);
    return Number.isFinite(explicit) && explicit > 0 ? explicit : 5;
}

/**
 * Симуляционные поля актёра для npcs-записи /plan (контракт тренировки: speed,
 * damage, reachFt, initiative). damage — формула лучшего оружия, reachFt — самая
 * дальняя уверенная атака (для лучника/пращи 30, для мили 5). hitChance не
 * передаём: сервер считает свою 0.65 — как и на тренировке.
 * @param {Token} token
 * @param {number|string|undefined} initiative из боевого трекера (может не быть)
 * @returns {object} часть payload для npcs[i]
 */
export function npcSimFields(token, initiative) {
    const fields = {};
    const walk = Number(token?.actor?.system?.attributes?.movement?.walk);
    if (Number.isFinite(walk) && walk > 0) fields.speed = walk;

    let damage = null;
    let reachFt = 0;
    for (const w of buildWeapons(token)) {
        if (w.sureFt > reachFt) reachFt = w.sureFt;
        const avg = damageAvg(w.damage);
        if (w.damage && (avg !== null) && (damage === null || avg > damageAvg(damage))) damage = w.damage;
    }
    if (damage) fields.damage = damage;
    if (reachFt) fields.reachFt = reachFt;

    const ini = Math.round(Number(initiative));
    if (Number.isFinite(ini)) fields.initiative = ini;
    return fields;
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