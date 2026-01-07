export function init() {
    /**
     * Hooks-скрипт для автоматического применения правила "минимум 10 на d20"
     * для Убеждения (Persuasion) и Обмана (Deception).
     * ВЕРСИЯ: Foundry VTT v11, DnD5e 3.3
     */

    // Хук для обработки броска навыка
    Hooks.on("dnd5e.rollSkill", async (actor, roll,skillKey) => {
        console.log("[dnd5e.rollSkill]",actor, skillKey,roll)

        const goldBard = actor.appliedEffects.find(i => i.name.toLowerCase().includes("златоуст"));
        console.log(goldBard)

        if(!goldBard) return ;
        // Проверяем, что это нужные навыки
        if (skillKey !== "per" && skillKey !== "dec") return;

        console.log(`Обрабатываем бросок навыка: ${skillKey}`, roll);
        let data = roll.result.split(' ')
        if (data[0] < 10) {
            data[0] = 10;
            let newRresult = data.join(' ');
            let nrt = 0;
            eval('nrt = '+newRresult)

            ChatMessage.create({
                content: `<b>${actor.name} ${roll.options.flavor}</b> Использует Златоуст. Новое значение: <b>${nrt}</b>=${newRresult}`,
                speaker: { alias: actor.name }
            });
            roll.toMessage = null
            console.log("Правило 'минимум 10' применено к броску", nrt, newRresult);
            return false;
        }
    });
}