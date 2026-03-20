export function init() {
    Hooks.on("midi-qol.postComputeCoverBonus", async (workflow) => {

        // Пропускаем, если это не атака оружием
        if (!workflow.item?.system?.actionType || workflow.item.system.actionType === "") return true;

        const attacker = workflow.actor;

        // Проверяем наличие способности Sharpshooter у атакующего (регистронезависимо)
        const hasSharpshooter = attacker.items.some(item =>
            item.name && item.name.toLowerCase().includes("sharpshooter")
        );

        if (!hasSharpshooter) {
            console.log('способность не найдена')
            return true;
        }

        // Для простоты обрабатываем только первую цель.
        // При необходимости можно доработать для нескольких целей (например, выбрать наихудшее укрытие).
        const targetToken = workflow.targets.first();
        if (!targetToken) return true;

        const targetActor = targetToken.actor;
        if (!targetActor) return true;

        let coverBonus = workflow.bonusAC;
        if (coverBonus === 0) return true; // укрытие отсутствует или не определено
        let attackBonus = 0;

        // Определяем новый бонус после применения Sharpshooter
        if (coverBonus === 2) {
            coverBonus = 0;
        } else if (coverBonus === 5) {
            coverBonus = 2;
        } else {
            return true;
        }

        console.log(`Sharpshooter: укрытие ${targetActor.name} уменьшено, нейтрализовано +${workflow.bonusAC} к АС`);

        workflow.bonusAC = coverBonus;
        if (game.user.isGM) {
            ui.notifications.info(`${attacker.name} использует Sharpshooter против ${targetActor.name}, игнорируя часть укрытия.`);
        }

        return true; // разрешаем продолжение обработки
    });
}
