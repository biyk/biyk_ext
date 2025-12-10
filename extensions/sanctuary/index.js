export function init() {
  Hooks.on("midi-qol.preAttackRoll", async (workflow) => {
      const attacker = workflow.actor;

      for (let targetToken of workflow.targets) {
          const targetActor = targetToken.actor;

          // Получаем все эффекты актёра
          const effects = targetActor.appliedEffects;
          console.log(targetActor.appliedEffects);
          const sanctuaryEffect = effects.find(e => {console.log(e.name.toLowerCase()); return e.name.toLowerCase().includes("sanctuary")});
          if (!sanctuaryEffect) continue;

          // Бросок проверки (DC 12)
          const roll = await new Roll("1d20 + @mod", { mod: attacker.data.data.abilities.wis?.mod || 0 }).roll({async: true});
          await roll.toMessage({ flavor: `${attacker.name} проверяет проверку на атаку через эффект Sanctuary` });

          if (roll.total < 12) {
              ui.notifications.info(`${attacker.name} не смог обойти Sanctuary и промахивается!`);

              // Отменяем атаку
              workflow._advantage = false;
              workflow.attackRoll = null;
              workflow.damageRoll = null;
              workflow.failedSanctuary = true;
              return false;
          }
      }
  });

}
