export function init() {
  Hooks.on("midi-qol.preAttackRoll", async (workflow) => {
    const attacker = workflow.actor;
    
    // Получаем тип существа разными способами
    let attackerType = "";
    
    // Способ 1: Из system.details.type (для D&D5e 3.3.0)
    if (attacker.system?.details?.type) {
      attackerType = String(attacker.system.details.type.value).toLowerCase();
    }
    // Способ 2: Из data.data.details.type
    else if (attacker.data?.data?.details?.type) {
      const typeValue = attacker.data.data.details.type;
      // Если это объект, берем value или преобразуем в строку
      if (typeof typeValue === 'object') {
        attackerType = String(typeValue.value || typeValue).toLowerCase();
      } else {
        attackerType = String(typeValue).toLowerCase();
      }
    }
    // Способ 3: Попробуем получить из traits
    else if (attacker.system?.traits?.creatureType) {
      attackerType = String(attacker.system.traits.creatureType).toLowerCase();
    }
    
    // Для отладки
    console.log("Attacker type:", attackerType, "from actor:", workflow);
    
    const validTypes = [
      "aberration", "аберрация",
      "beast", "зверь", "bestia",
      "celestial", "небожитель",
      "undead", "нежить",
      "fey", "фея",
      "elemental", "элементаль"
    ];
    
    // Проверяем, является ли атакующий одним из указанных типов
    const isCorrectType = validTypes.some(type => attackerType.includes(type.toLowerCase()));
    if (!isCorrectType) {
      console.log("Attacker type not in valid types:", attackerType);
      return;
    }
    
    // Проверяем цели
    for (let targetToken of workflow.targets) {
      const targetActor = targetToken.actor;
      
      // Ищем эффект Protection from Evil and Good
      const effects = targetActor.appliedEffects || [];
      console.log(effects);
      const protectionEffect = effects.find(e => {
        if (!e?.name) return false;
        const name = e.name.toLowerCase();
        console.log(name);
        return name.includes("protection from evil and good") || 
               name.includes("защита от зла и добра") ||
               name.includes("защита от добра и зла") ||
               name.includes("protection from good and evil");
      });
      
      if (!protectionEffect) {
        console.log("No Protection from Evil and Good effect found on", targetToken.name);
        continue;
      } else {
        console.log("Found effect:", protectionEffect.name);
      
        if (protectionEffect.name.includes('Концентрация')) return;
        // Устанавливаем помеху на атаку
        workflow.disadvantage = true;
        
        console.log("Disadvantage applied for attack on", targetToken.name);
      }
      

      
      return; // Достаточно одного подходящего эффекта
    }
  });


}

