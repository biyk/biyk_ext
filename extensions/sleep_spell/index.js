// extensions/sleep_spell/index.js
export function init() {
    Hooks.on("dnd5e.useItem", async (item, config, options) => {
        if (!item.name.toLowerCase().includes("sleep")) return;

        const spellLevel = item.system.level;
        if (!spellLevel) return;

        const baseDice = 5;
        const extraDicePerLevel = 2;
        const extraLevels = Math.max(0, spellLevel - 1);
        const totalDice = baseDice + (extraLevels * extraDicePerLevel);

        const roll = new Roll(`${totalDice}d8`);
        await roll.roll({ async: true });
        await roll.toMessage({
            flavor: `Заклинание "Сон" - пул хитов (${totalDice}к8)`,
            speaker: ChatMessage.getSpeaker({ actor: item.actor })
        });

        let hpPool = roll.total;

        const targets = Array.from(game.user.targets);
        if (targets.length === 0) {
            ui.notifications.warn("Нет выбранных целей!");
            return;
        }

        const targetCenter = targets[0];
        const centerPos = { x: targetCenter.x, y: targetCenter.y };
        const range = 20 * canvas.scene.grid.size;

        const allTokens = canvas.tokens.placeables.filter(token => {
            if (!token.actor) return false;
            const dist = Math.sqrt(
                Math.pow(token.x - centerPos.x, 2) + Math.pow(token.y - centerPos.y, 2)
            );
            return dist <= range;
        });

        const validCreatures = [];

        for (const token of allTokens) {
            const actor = token.actor;
            if (!actor) continue;

            const currentHp = actor.system.attributes.hp.value;
            const maxHp = actor.system.attributes.hp.max;

            if (currentHp > hpPool) continue;

            const types = actor.system.details?.type?.toLowerCase() || "";
            const isUndead = types.includes("undead") || types.includes("нежить");

            const isImmuneToCharm = actor.system.traits?.ci?.value?.some?.(
                ci => ci.toLowerCase().includes("charm") || ci.toLowerCase().includes("очарование")
            ) || false;

            if (isUndead || isImmuneToCharm) continue;

            validCreatures.push({
                token,
                actor,
                currentHp,
                maxHp
            });
        }

        validCreatures.sort((a, b) => a.currentHp - b.currentHp);

        const unconsciousEffect = CONFIG.statusEffects.find(e => 
            e.name?.toLowerCase() === "unconscious"
        );

        if (!unconsciousEffect) {
            ui.notifications.error("Не найден эффект 'Unconscious' в системе!");
            return;
        }

        const affectedCreatures = [];

        for (const creature of validCreatures) {
            if (creature.currentHp > hpPool) break;

            hpPool -= creature.currentHp;
            affectedCreatures.push(creature);

            try {
                let effectToApply = { ...unconsciousEffect };
                if (!effectToApply._id) {
                    effectToApply._id = foundry.utils.randomID();
                }
                await creature.token.toggleEffect(effectToApply, { active: true });
            } catch (error) {
                console.error(`Sleep | Ошибка при применении эффекта к ${creature.token.name}:`, error);
            }
        }

        let message = `Применено к ${affectedCreatures.length} существам:\\n`;
        for (const c of affectedCreatures) {
            message += `- ${c.token.name} (${c.currentHp} HP)\\n`;
        }
        message += `Остаток пула HP: ${hpPool}`;

        ChatMessage.create({
            content: message,
            speaker: ChatMessage.getSpeaker({ actor: item.actor }),
            whisper: [game.user.id]
        });

        ui.notifications.info(`Заклинание "Сон" применено к ${affectedCreatures.length} существам!`);
    });
}