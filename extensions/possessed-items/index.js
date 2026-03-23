//Data\modules\biyk_ext\extensions\possessed-items\index.js
export function init() {
    Hooks.on("dnd5e.useItem", async (item, config, options) => {
        if (item.name !== "Власть над предметом") return;

        const casterActor = item.parent;
        if (!casterActor) {
            console.warn("PossessedItems: нет актёра");
            return;
        }

        const spellDC = casterActor.system.attributes.spelldc;
        if (!spellDC) {
            ui.notifications.error("У заклинателя не определено DC заклинаний.");
            return;
        }

        let targets = [];
        if (config?.targets && config.targets.size) {
            targets = Array.from(config.targets);
        } else if (game.user.targets.size) {
            targets = Array.from(game.user.targets);
        }

        if (targets.length === 0) {
            ui.notifications.warn("Нет целей для заклинания «Власть над предметом».");
            return;
        }

        for (let targetToken of targets) {
            const targetActor = targetToken.actor;
            if (!targetActor) continue;
            if (casterActor.id === targetActor.id) {
                ui.notifications.warn("Заклинатель и цель не могут быть одним существом.");
                continue;
            }

            try {
                console.log("PossessedItems: rolling save");
                const saveRoll = await targetActor.rollAbilitySave("str", { chatMessage: true });
                const saveTotal = saveRoll.total;
                const saveSuccess = saveTotal >= spellDC;

                if (saveSuccess) {
                    await ChatMessage.create({
                        content: `<strong>${targetActor.name}</strong> успешно сопротивляется заклинанию «Власть над предметом»!`,
                        speaker: ChatMessage.getSpeaker({ actor: targetActor })
                    });
                    continue;
                }

                const weapons = targetActor.items.filter(i => i.type === "weapon" && i.system.equipped);
                if (weapons.length === 0) {
                    await ChatMessage.create({
                        content: `<strong>${targetActor.name}</strong> проваливает спасбросок, но у него нет экипированного оружия, которое можно отобрать.`,
                        speaker: ChatMessage.getSpeaker({ actor: targetActor })
                    });
                    continue;
                }

                const weapon = weapons[0];
                const weaponData = weapon.toObject();

                await targetActor.deleteEmbeddedDocuments("Item", [weapon.id]);
                await casterActor.createEmbeddedDocuments("Item", [weaponData]);

                await ChatMessage.create({
                    content: `<strong>${targetActor.name}</strong> проваливает спасбросок против <strong>Одержимых предметов</strong>!<br>
                          ${casterActor.name} отбирает <strong>${weapon.name}</strong> и забирает себе.`,
                    speaker: ChatMessage.getSpeaker({ actor: casterActor })
                });
            } catch (err) {
                console.error("PossessedItems: ошибка", err);
                ui.notifications.error("Произошла ошибка при обработке заклинания.");
            }
        }
    });
}