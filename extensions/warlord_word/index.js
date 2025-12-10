export function init() {
    Hooks.on("midi-qol.RollComplete", async (workflow) => {
    const item = workflow.item;
    if (!item) return;
    if (item.name !== "Вдохновляющее слово") return;

    const caster = item.actor;
    const targets = workflow.targets;

    if (targets.size === 0) {
        ui.notifications.warn("Выберите хотя бы одну цель для Вдохновляющего слова!");
        return;
    }

    for (let targetToken of targets) {
        const targetActor = targetToken.actor;
        if (!targetActor) continue;

        // Определяем кубик здоровья цели
        let dieValue = 1; // дефолтное значение
        const hitDice = targetActor.system.attributes.hp.formula;
        if (hitDice) {
        const match = hitDice.match(/d(\d+)/);
        if (match) dieValue = parseInt(match[1]);
        } else {
            for (let _class of Object.values(targetActor.classes)) {
                let classHitDice = _class.system?.hitDice;
                if (classHitDice) {
                    const match = classHitDice.match(/d(\d+)/);
                    if (match) dieValue = Math.max(parseInt(match[1]), dieValue);
                }
            }
        }
        console.log('dieValue',targetActor, dieValue);

        // Модификатор мудрости заклинателя
        const wisdomMod = caster.data.data.abilities.wis.mod;

        // Лечение: кубик + модификатор мудрости
        const healAmount = dieValue + wisdomMod;

        // Применяем лечение, не превышая максимум HP
        const newHp = Math.min(
        targetActor.data.data.attributes.hp.value + healAmount,
        targetActor.data.data.attributes.hp.max
        );
        await targetActor.update({ "data.attributes.hp.value": newHp });

        // Сообщение в чат
        ChatMessage.create({
        speaker: { actor: caster },
        content: `${caster.name} использует Вдохновляющее слово на ${targetActor.name} и восстанавливает ${healAmount} хитов!`
        });
    }
    });


}
