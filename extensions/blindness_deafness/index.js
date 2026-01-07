export function init() {
    Hooks.on("dnd5e.useItem", async (item, config, options) => {
        // Проверяем, является ли предмет заклинанием Blindness/Deafness (регистр не важен)
        if (!item.name.toLowerCase().includes("blindness/deafness")) return;

        // Получаем цели
        const targets = game.user.targets;
        if (!targets || targets.length === 0) {
            ui.notifications.warn("Нет выбранных целей!");
            return;
        }

        // Находим стандартные статус-эффекты в системе.
        // Они хранятся в CONFIG.statusEffects[citation:5].
        const blindedEffect = CONFIG.statusEffects.find(e => e.name === "Blinded");
        const deafenedEffect = CONFIG.statusEffects.find(e => e.name === "Deafened");

        // Создаём диалоговое окно для выбора эффекта
        const choice = await new Promise((resolve) => {
            new Dialog({
                title: "Выберите эффект для Blindness/Deafness",
                content: `
        <div style="padding: 10px;">
          <p>Выберите эффект для применения к цели:</p>
          <div style="display: flex; flex-direction: column; gap: 10px; margin: 10px 0;">
            <label>
              <input type="radio" name="effectChoice" value="blinded" checked>
              <strong>Слепота (Blinded)</strong>
            </label>
            <label>
              <input type="radio" name="effectChoice" value="deafened">
              <strong>Глухота (Deafened)</strong>
            </label>
          </div>
        </div>
      `,
                buttons: {
                    ok: {
                        label: "Применить",
                        callback: (html) => {
                            const selected = html.find('input[name="effectChoice"]:checked').val();
                            resolve(selected);
                        }
                    },
                    cancel: {
                        label: "Отмена",
                        callback: () => resolve(null)
                    }
                },
                default: "ok"
            }).render(true);
        });

        // Если пользователь отменил выбор
        if (!choice) return;

        // Определяем, какой эффект из CONFIG применять
        const chosenEffect = choice === 'blinded' ? blindedEffect : deafenedEffect;

        if (!chosenEffect) {
            ui.notifications.error(`Не удалось найти данные для эффекта "${choice}" в системе.`);
            return;
        }

        // Применяем эффект к каждой цели
        for (const target of targets) {
            const token = target;
            const actor = target.actor;
            if (!actor) continue;
            if (!token) continue;

            try {
                // Метод toggleEffect применяет или снимает эффект с токена.
                // Мы передаём ID эффекта и флаг true (применить).
                let id = chosenEffect.id;
                let statusEffect = CONFIG.statusEffects.find(se => se.id === id);if (!statusEffect._id) { // fiddle for CE effects
                    statusEffect._id = foundry.utils.randomID();
                }
                await token.toggleEffect(chosenEffect, {active: true});


                // Опционально: вывести сообщение в чат
                // ChatMessage.create({
                //   speaker: ChatMessage.getSpeaker({actor: item.actor}),
                //   content: `Применяет ${choice === 'blinded' ? 'Слепоту' : 'Глухоту'} к ${token.name}`
                // });

            } catch (error) {
                console.error(`Ошибка при применении эффекта к ${token.name}:`, error);
                ui.notifications.error(`Не удалось применить эффект к ${token.name}`);
            }
        }

        // Уведомление об успешном применении
        ui.notifications.info(`Эффект "${choice === 'blinded' ? 'Слепота' : 'Глухота'}" успешно применён к целям!`);
    });

}

