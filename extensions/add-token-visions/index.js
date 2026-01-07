export function init() {

    /* ===============================
     * WHITELIST DETECTION RULES
     * =============================== */
    const DETECTION_RULES = [
        {
            detectionId: "detectMagic",
            match: name => name.includes("detect magic")
        },
        {
            detectionId: "detectEvilAndGood",
            match: name => name.includes("detect evil and good")
        },
        {
            detectionId: "detectPoisonAndDisease",
            match: name => name.includes("detect poison and disease")
        }
    ];

    // Для быстрого доступа
    const RULE_IDS = new Set(DETECTION_RULES.map(r => r.detectionId));


    /* ===============================
     * ПЕРЕСЧЁТ (ТОЛЬКО WHITELIST)
     * =============================== */
    async function recalcDetections(actor) {
        if (!actor) return;

        const effects = actor.appliedEffects ?? [];

        // какие детекты ИЗ СПИСКА должны быть активны
        const shouldBeEnabled = new Set();

        for (const effect of effects) {
            const name = effect.name?.toLowerCase() ?? "";
            for (const rule of DETECTION_RULES) {
                if (rule.match(name)) {
                    shouldBeEnabled.add(rule.detectionId);
                }
            }
        }

        for (const token of actor.getActiveTokens()) {
            const updatedModes = token.document.detectionModes.map(mode => {

                // ⛔ НЕ ИЗ НАШЕГО СПИСКА — НЕ ТРОГАЕМ
                if (!RULE_IDS.has(mode.id)) return mode;

                const enable = shouldBeEnabled.has(mode.id);
                if (mode.enabled === enable) return mode;

                return { ...mode, enabled: enable };
            });

            await token.document.update({ detectionModes: updatedModes });
        }
    }


    /* ===============================
     * ХУКИ
     * =============================== */

    Hooks.on("createActiveEffect", async (effect) => {
        const actor = effect.parent;
        if (!actor) return;
        await recalcDetections(actor);
    });

    Hooks.on("deleteActiveEffect", async (effect) => {
        const actor = effect.parent;
        if (!actor) return;
        await recalcDetections(actor);
    });

}
