export function init() {
    Hooks.on("midi-qol.preAttackRoll", async (workflow) => {
        // Пропускаем если это не атака оружием
        if (!workflow.item?.system?.actionType || workflow.item.system.actionType === "") return true;

        const attacker = workflow.actor;
        let attackCanceled = false;

        for (let targetToken of workflow.targets) {
            const targetActor = targetToken.actor;

            // Ищем эффект Уклонение (регистронезависимо)
            const avoidEffect = targetActor.appliedEffects.find(e =>
                e.name.toLowerCase().includes("уклонение")
            );

            if (!avoidEffect) continue;

            if (workflow.disadvantage) {
                // Если уже есть помеха - ничего не меняем
                continue;
            } else if (workflow.advantage) {
                // Если есть преимущество - нейтрализуем его
                workflow.advantage = false;
                workflow.disadvantage = false;
                console.log("Преимущество нейтрализовано Уклонением");
            } else {
                // Добавляем помеху
                workflow.disadvantage = true;
                console.log("Добавлена помеха от Уклонения");
            }

            // Показываем уведомление для GM
            if (game.user.isGM) {
                ui.notifications.info(`${targetActor.name} использует Уклонение! Атака ${attacker.name} получает помеху.`);
            }
        }

        return true;
    });


}

