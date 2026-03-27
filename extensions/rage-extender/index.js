export function init() {
    const RAGE_EFFECT_NAMES = ["ярость", "rage"];
    const MAX_DURATION = 600;
    const EXTEND_SECONDS = 6;
    const DEBUG = true;

    function log(...args) {
        if (DEBUG) console.log("[RageExtender]", ...args);
    }

    function findRageEffect(actor) {
        if (!actor) {
            log("findRageEffect: actor is null/undefined");
            return null;
        }
        
        const allEffects = actor.appliedEffects;
        log(`findRageEffect: ищу эффект ярости у ${actor.name}. Всего эффектов: ${allEffects?.size || 0}`);
        
        const found = allEffects.find(e => {
            const label = e.label?.toLowerCase() || "";
            const name = e.name?.toLowerCase() || "";
            log(`  Проверяю эффект: label="${e.label}", name="${e.name}", match=${RAGE_EFFECT_NAMES.some(n => label.includes(n) || name.includes(n))}`);
            return RAGE_EFFECT_NAMES.some(n => label.includes(n) || name.includes(n));
        });
        
        if (!found) {
            log(`findRageEffect: эффект ярости НЕ найден`);
        } else {
            log(`findRageEffect: найден эффект "${found.label}" с id=${found.id}`);
        }
        
        return found;
    }

    async function extendRageDuration(actor, source) {
        log(`extendRageDuration: вызвано для ${actor?.name} от "${source}"`);
        
        const rageEffect = findRageEffect(actor);
        if (!rageEffect) {
            log(`extendRageDuration: НЕ продлеваем - нет эффекта ярости`);
            return;
        }

        const currentDuration = rageEffect.duration;
        log(`extendRageDuration: текущий duration=`, currentDuration);
        
        if (!currentDuration) {
            log("extendRageDuration: duration отсутствует");
            return;
        }
        
        if (currentDuration.type !== "seconds") {
            log(`extendRageDuration: тип duration = "${currentDuration.type}", ожидался "seconds"`);
            return;
        }

        const remaining = currentDuration.remaining;
        log(`extendRageDuration: осталось секунд = ${remaining}`);
        
        if (remaining === undefined) {
            log("extendRageDuration: remaining = undefined");
            return;
        }

        const newDuration = Math.min(remaining + EXTEND_SECONDS, MAX_DURATION);
        log(`extendRageDuration: ${remaining} + ${EXTEND_SECONDS} = ${newDuration} (max: ${MAX_DURATION})`);

        await rageEffect.update({
            "duration.seconds": newDuration,
            "duration.startTime": game.time.worldTime
        });

        log(`[RageExtender] ✓ ${actor.name} продлил ярость на ${EXTEND_SECONDS}с (${source}). Всего: ${newDuration}с`);
    }

    Hooks.on("midi-qol.postDamageRollComplete", async (workflow) => {
        log("midi-qol.postDamageRollComplete: начало", {
            actor: workflow.actor?.name, 
            hitTargets: workflow.hitTargets?.size,
            item: workflow.item?.name,
            damageTotal: workflow.damageTotal
        });

        if (!workflow.hitTargets?.size) {
            log("midi-qol.postDamageRollComplete: не попали - выходим");
            return;
        }
        
        // Сначала проверяем цель (получила урон)
        for (const target of workflow.hitTargets) {
            if (target?.actor) {
                log(`Проверяем цель ${target.actor.name} на ярость`);
                await extendRageDuration(target.actor, "получение урона");
            }
        }
        
        // Потом проверяем атакующего
        log(`Проверяем атакующего ${workflow.actor.name} на ярость`);
        await extendRageDuration(workflow.actor, "атака");
    });

    Hooks.on("dnd5e.rollAbilityTest", async (actor, ability, abilityId) => {
        log("dnd5e.rollAbilityTest: начало", { actor: actor?.name, ability ,abilityId});
        
        if (!actor) {
            log("dnd5e.rollAbilityTest: нет actor");
            return;
        }
        if (abilityId !== "str") {
            log(`dnd5e.rollAbilityTest: ability = "${abilityId}", не "str" - пропускаем`);
            return;
        }
        
        await extendRageDuration(actor, "проверка силы");
    });
    Hooks.on("dnd5e.rollSkill", async (actor, ability, abilityId) => {
        log("dnd5e.rollSkill: начало", { actor: actor?.name, ability ,abilityId});

        if (!actor) {
            log("dnd5e.rollSkill: нет actor");
            return;
        }
        if (abilityId !== "ath") {
            log(`dnd5e.rollSkill: ability = "${abilityId}", не "ath" - пропускаем`);
            return;
        }

        await extendRageDuration(actor, "проверка силы");
    });

    log("RageExtender инициализирован");
}
