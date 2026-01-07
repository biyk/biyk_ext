export function init() {
  Hooks.on("midi-qol.RollComplete", async (workflow) => {
    // Только атаки оружием
    if (!workflow.item) return;
    const actionType = workflow.item.system.actionType;
    if (actionType !== "mwak" && actionType !== "rwak") return;

    // Проверка попадания
    const initialHit = workflow.hitTargets.size > 0;
    if (initialHit) return; // попал — ничего не делаем

    const attacker = workflow.actor;
    const attackToken = workflow.token;
    const currentRound = game.combat?.round ?? 0;
    console.log(attacker);


    // Поиск союзников в радиусе 15 футов
    const allies = canvas.tokens.placeables.filter(t => {
      if (!t.actor) return false;
      if (t.document.disposition !== attackToken.document.disposition) return false;
      if (t.id === attackToken.id) return false;
      const dist = MidiQOL.getDistance(t, attackToken, false);
      return dist !== null && dist <= 15;
    });

    if (allies.length === 0) {
      console.log("Нет союзников поблизости");
      return;
    }

    // Ищем союзников с фитом "Лидер - Наставник"
    const helpers = allies.filter(t =>
      t.actor.items.find(i => i.name === "Лидер - Наставник")
    );

    if (helpers.length === 0) {
      console.log("Нет союзников с фитом Лидер - Наставник");
      return;
    }

    // Берем первого найденного
    const helperToken = helpers[0];
    const helperActor = helperToken.actor;

    // Проверяем наличие доступной реакции
    let canReact = true;
    const midiActions = helperActor.getFlag("midi-qol", "actions");

    if (midiActions && typeof midiActions === "object") {
      const reactionInfo = midiActions.reaction;
      const currentRound = game.combat?.round ?? 0;

      if (reactionInfo) {
        // Если реакция уже использована в этом раунде
        if (reactionInfo.round === currentRound) canReact = false;
      }
    }

    if (!canReact) {
      console.log(`${helperActor.name} уже потратил реакцию`);
      return;
    }

   // Диалог использования реакции (V11 синтаксис)
    const useReaction = await Dialog.confirm({
      title: "Лидер – Наставник",
      content: `<p>${helperActor.name}, хотите использовать реакцию, чтобы помочь ${attacker.name}? Добавляется 1d4 к атаке.</p>`
    });

    if (!useReaction) return;

    // Отмечаем реакцию как использованную
    const updatedActions = foundry.utils.mergeObject(midiActions || {}, {
      reaction: { round: currentRound }
    });
    await helperActor.setFlag("midi-qol", "actions", updatedActions);

    // Кидаем 1d4
    const d4Roll = await (new Roll("1d4")).roll({ async: true });
    await d4Roll.toMessage({
      flavor: `${helperActor.name} использует "Лидер – Наставник" и добавляет ${d4Roll.total} к атаке ${attacker.name}`
    });

    // Повторная проверка попадания
    const targetToken = workflow.targets.first();
    if (!targetToken) return;
    const targetActor = targetToken.actor;

    const newAttackTotal = workflow.attackRoll.total + d4Roll.total;
    const AC = targetActor.system.attributes.ac.value;

    const hitNow = newAttackTotal >= AC;

    if (!hitNow) {
      ChatMessage.create({
        speaker: { actor: helperActor },
        content: `${attacker.name} промахивается даже с помощью ${helperActor.name}.`
      });
      return;
    }

    // Попадание — наносим урон
    ChatMessage.create({
      speaker: { actor: helperActor },
      content: `${helperActor.name} помогает ${attacker.name}! Повторная проверка успешна — наносим урон.`
    });

    

    // подготовка для applyTokenDamage
    const dmgList = [{ damage: workflow.damageTotal, type: workflow.defaultDamageType }];
    const totalDamage = workflow.damageTotal;
    const targetsSet = new Set([ targetToken ]);
    const itemUuid = workflow.item?.uuid ?? undefined;
    const saveSet = new Set(); // если нет спасбросков
    const options = { workflow }; // передаём workflow чтобы midi-qol корректно применил урон

    await MidiQOL.applyTokenDamage(dmgList, totalDamage, targetsSet, itemUuid, saveSet, options);
  });
}

