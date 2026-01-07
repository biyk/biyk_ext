/**
 * Функция проверки фокусировки/реагентов для волшебника и амулета для жреца
 * @returns {boolean} true если можно кастовать, false если нет
 */
async function checkSpellComponents(actor, item) {
  const actorClasses = actor.classes || {};
  const isWizard = actorClasses.wizard !== undefined;
  const isCleric = actorClasses.cleric !== undefined;

  const components = item.system.components;
  const properties = item.system.properties;

  // Если нет материального компонента, проверка не нужна
  if (!properties.has("material")) return true;

  const items = actor.items;
  
  // Проверка для волшебника
  if (isWizard) {
    let hasFocus = false;
    let hasReagentBag = false;

    for (const actorItem of items) {
      if (!actorItem.system.equipped) continue;
      if (actorItem.system.properties?.foc) {
        hasFocus = true;
        console.log(`[WizardComponents] Найдена экипированная фокусировка: "${actorItem.name}"`);
        break;
      }
    }

    for (const actorItem of items) {
      if (!actorItem.system.equipped) continue;
      if (actorItem.name.toLowerCase().includes("сумка с реагентами")) {
        hasReagentBag = true;
        console.log(`[WizardComponents] Найдена экипированная сумка с реагентами: "${actorItem.name}"`);
        break;
      }
    }

    if (!hasFocus && !hasReagentBag) {
      return false;
    }
  }

  // Проверка для жреца
  if (isCleric) {
    let hasAmulet = false;

    for (const actorItem of items) {
      if (!actorItem.system.equipped) continue;
      if (actorItem.name.toLowerCase().includes("амулет")) {
        hasAmulet = true;
        console.log(`[WizardComponents] Найден экипированный амулет: "${actorItem.name}"`);
        break;
      }
    }

    if (!hasAmulet) {
      return false;
    }
  }

  return true;
}

/**
 * Хук для проверки возможности использования заклинания
 */
Hooks.on("dnd5e.preUseItem", async (item, config, options) => {
  if (item.type !== "spell") return true;

  const actor = item.actor;
  console.log(`[WizardComponents] Попытка использовать заклинание: ${item.name}`);

  const canCast = await checkSpellComponents(actor, item);

  if (!canCast) {
    const spellLevel = item.system.level;
    const damageHP = Math.max(spellLevel, 1);

    const currentHP = actor.system.attributes.hp.value;
    const newHP = Math.max(currentHP - damageHP, 0);

    await actor.update({ "system.attributes.hp.value": newHP });
    console.log(`[WizardComponents] ${actor.name} теряет ${damageHP} HP. Текущее HP: ${newHP}`);

    ui.notifications.warn(`Вы кастуете ${item.name} без нужной фокусировки/амулета/сумки с реагентами! Потеряно ${damageHP} HP.`);
  }

  return canCast;
});
