//Data\modules\biyk_ext\extensions\sanctuary\index.js
export function init() {
    Hooks.on("midi-qol.preAttackRoll", async (workflow) => {
        const attacker = workflow.actor;

        for (let targetToken of workflow.targets) {
            const targetActor = targetToken.actor;

            // Получаем все эффекты актёра
            const effects = targetActor.appliedEffects;
            //console.log(targetActor);
            const sanctuaryEffect = effects.find(e => {console.log(e.name.toLowerCase()); return e.name.toLowerCase().includes("sanctuary")});
            if (!sanctuaryEffect) continue;

            const mod = targetActor.system.abilities.wis.mod;
            const master = targetActor.system.attributes.prof;
            const DC = 8 + master + mod;
            //console.log('sanctuary',8 , master , mod)
            // Бросок проверки (DC 12)
            const roll = await new Roll("1d20 + @mod", { mod: attacker.data.data.abilities.wis?.mod || 0 }).roll({async: true});
            await roll.toMessage({ flavor: `${attacker.name} проверяет проверку на атаку через эффект Sanctuary` });

            if (roll.total < DC) {
                ui.notifications.info(`${attacker.name} не смог обойти Sanctuary и промахивается!`);

                // Отменяем атаку
                workflow._advantage = false;
                workflow.attackRoll = null;
                workflow.damageRoll = null;
                workflow.failedSanctuary = true;
                return false;
            } else {
                //ui.notifications.info(`${attacker.name} обошел с результатом ${roll.total} > ${DC}  Sanctuary и попал!`);

            }
        }
    });

}
