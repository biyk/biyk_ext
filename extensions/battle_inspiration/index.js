export function init() {
    Hooks.on("midi-qol.RollComplete", async (workflow) => {
        // Только атаки оружием
        if (!workflow.item) return;
        const actionType = workflow.item.system.actionType;
        if (actionType !== "mwak" && actionType !== "rwak") return;

        // Проверка попадания
        const initialHit = workflow.hitTargets.size > 0;
        if (!initialHit) return; // промах — ничего не делаем

        const attacker = workflow.actor;
        const attackToken = workflow.token;
        const currentRound = game.combat?.round ?? 0;

        // Получаем текущего пользователя
        const currentUser = game.user;

        // Проверяем, что текущий пользователь GM или принадлежит атакующему
        const isGM = currentUser.isGM;
        const ownsAttacker = attacker.isOwner;

        if (!isGM && !ownsAttacker) {
            console.log("Скрипт выполняется только для владельца актера или GM");
            return;
        }

        // Если это враг - выходим
        if (attackToken.document.disposition !== 1) {
            console.log("Атакующий - враг");
            return;
        }

        // Ищем союзников с фитом "Боевое вдохновение"
        const helpers = canvas.tokens.placeables.filter(t => {
            if (!t.actor) return false;

            // Проверяем наличие предмета "Боевое вдохновение"
            const hasInspiration = t.actor.items.find(i => i.name === "Боевое вдохновение");
            if (!hasInspiration) return false;
            console.log(t.actor);

            // Проверяем права доступа для скрипта
            const tokenOwner = t.actor.isOwner;

            return isGM || tokenOwner;
        });

        if (helpers.length === 0) {
            console.log("Нет доступных союзников с фитом Боевое вдохновение");
            return;
        }

        // Для каждого владельца навыка показываем диалог
        for (const helperToken of helpers) {
            const helperActor = helperToken.actor;

            // Проверяем наличие доступной реакции
            let canReact = true;
            const midiActions = helperActor.getFlag("midi-qol", "actions");

            if (midiActions && typeof midiActions === "object") {
                const reactionInfo = midiActions.reaction;
                if (reactionInfo && reactionInfo.round === currentRound) {
                    console.log(`${helperActor.name} уже потратил реакцию в этом раунде`);
                    canReact = false;
                }
            }

            if (!canReact) continue;

            // Определяем, кому показывать диалог
            const showToUser = helperActor.isOwner ? currentUser :
                game.users.find(u => u.isGM && u.active);

            if (!showToUser) continue;

            // Показываем диалог владельцу навыка
            let useReaction = false;

            if (showToUser === currentUser) {
                // Показываем текущему пользователю
                useReaction = await Dialog.confirm({
                    title: "Боевое вдохновение",
                    content: `<p><strong>${helperActor.name}</strong>, хотите использовать реакцию "Боевое вдохновение", чтобы помочь <strong>${attacker.name}</strong>?</p>`,
                    yes: () => true,
                    no: () => false,
                    defaultYes: false
                });
            }

            if (!useReaction) continue;

            // Отмечаем реакцию как использованную
            const updatedActions = foundry.utils.mergeObject(midiActions || {}, {
                reaction: { round: currentRound }
            });
            await helperActor.setFlag("midi-qol", "actions", updatedActions);

            // Используем навык "Боевое вдохновение"
            await useCombatInspiration(helperActor, attacker, workflow);

            // Прерываем цикл после первого использованного навыка
            break;
        }
    });
}

async function useCombatInspiration(helperActor, attacker, workflow) {
    console.log(`Используем Боевое вдохновение от ${helperActor.name} для ${attacker.name}`);

    // 1. Создаем чат-сообщение
    const chatContent = `
    <div class="midi-qol-flex-container">
      <div class="midi-qol-target-npc midi-qol-hits">
        <div class="midi-qol-item-name"><strong>${helperActor.name}</strong> использует <strong>Боевое вдохновение</strong> чтобы помочь ${attacker.name}!</div>
      </div>
    </div>
  `;

    await ChatMessage.create({
        content: chatContent,
        speaker: ChatMessage.getSpeaker({ actor: helperActor }),
        flavor: "Боевое вдохновение"
    });

    // 2. Находим предмет "Боевое вдохновение"
    const inspirationItem = helperActor.items.find(i => i.name === "Боевое вдохновение");

    if (inspirationItem) {
        try {
            // Пытаемся использовать предмет, если он имеет макрос
            if (inspirationItem.type === "feat" || inspirationItem.type === "spell") {
                await inspirationItem.use();
            }
        } catch (err) {
            console.warn("Не удалось автоматически использовать предмет:", err);
        }
    }


    console.log("Боевое вдохновение успешно применено!");
}
