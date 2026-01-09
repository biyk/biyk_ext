export function init() {
    Hooks.on("dnd5e.useItem", async (item, config, options) => {
        console.log(item, config, options);

        // Проверяем, является ли предмет заклинанием Enhance Ability
        // Можно адаптировать название под свою локализацию
        if (!item.name.toLowerCase().includes("enhance ability") &&
            !item.name.toLowerCase().includes("усиление способности")) return;

        // Получаем цели
        const targets = game.user.targets;
        if (!targets || targets.length === 0) {
            ui.notifications.warn("Нет выбранных целей!");
            return;
        }

        // Создаём диалоговое окно для выбора эффекта
        const choice = await new Promise((resolve) => {
            new Dialog({
                title: "Выберите эффект для Enhance Ability",
                content: `
        <div style="padding: 10px;">
          <p>Выберите эффект для применения к цели:</p>
          <div style="display: flex; flex-direction: column; gap: 10px; margin: 10px 0;">
            <label>
              <input type="radio" name="effectChoice" value="bullsStrength" checked>
              <strong>Бычья сила</strong> - преимущество к проверкам Силы, удвоенная грузоподъёмность
            </label>
            <label>
              <input type="radio" name="effectChoice" value="catsGrace">
              <strong>Кошачья грация</strong> - преимущество к проверкам Ловкости, игнорирование падения с малой высоты
            </label>
            <label>
              <input type="radio" name="effectChoice" value="foxsCunning">
              <strong>Лисья хитрость</strong> - преимущество к проверкам Интеллекта
            </label>
            <label>
              <input type="radio" name="effectChoice" value="bearsEndurance">
              <strong>Медвежья стойкость</strong> - преимущество к проверкам Выносливости + 2d6 временных ПЗ
            </label>
            <label>
              <input type="radio" name="effectChoice" value="eaglesSplendor">
              <strong>Орлиное великолепие</strong> - преимущество к проверкам Харизмы
            </label>
            <label>
              <input type="radio" name="effectChoice" value="owlsWisdom">
              <strong>Совиная мудрость</strong> - преимущество к проверкам Мудрости
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

        // Получаем длительность заклинания
        const duration = item.system.duration?.value || 0;
        const durationUnit = item.system.duration?.units || "hours";

        // Применяем эффект к каждой цели
        for (const target of targets) {
            const token = target;
            const actor = target.actor;
            if (!actor) continue;

            try {
                // Создаём эффект в зависимости от выбора
                let effectData;
                switch(choice) {
                    case 'bullsStrength':
                        effectData = await createBullsStrengthEffect(item, duration, durationUnit);
                        break;
                    case 'catsGrace':
                        effectData = await createCatsGraceEffect(item, duration, durationUnit);
                        break;
                    case 'foxsCunning':
                        effectData = await createFoxsCunningEffect(item, duration, durationUnit);
                        break;
                    case 'bearsEndurance':
                        effectData = await createBearsEnduranceEffect(item, duration, durationUnit, actor);
                        break;
                    case 'eaglesSplendor':
                        effectData = await createEaglesSplendorEffect(item, duration, durationUnit);
                        break;
                    case 'owlsWisdom':
                        effectData = await createOwlsWisdomEffect(item, duration, durationUnit);
                        break;
                    default:
                        return;
                }

                // Применяем эффект к актёру
                await actor.createEmbeddedDocuments("ActiveEffect", [effectData]);

                ui.notifications.info(`Эффект "${getEffectName(choice)}" применён к ${token.name}`);

            } catch (error) {
                console.error(`Ошибка при применении эффекта к ${token.name}:`, error);
                ui.notifications.error(`Не удалось применить эффект к ${token.name}`);
            }
        }
    });
}

// Функции создания эффектов
async function createBullsStrengthEffect(sourceItem, duration, durationUnit) {
    const effect = {
        label: "Бычья сила (Enhance Ability)",
        icon: "icons/svg/upgrade.svg", // Можно заменить на свою иконку
        origin: sourceItem.uuid,
        duration: {
            seconds: convertToSeconds(duration, durationUnit),
            startTime: game.time.worldTime
        },
        flags: {
            core: {
                statusId: "bullsStrength"
            },
            dnd5e: {
                effectType: "spell"
            }
        },
        changes: [
            {
                key: "flags.dnd5e.advantage.ability.save.str",
                mode: CONST.ACTIVE_EFFECT_MODES.ADD,
                value: 1,
                priority: 20
            },
            {
                key: "flags.dnd5e.advantage.ability.check.str",
                mode: CONST.ACTIVE_EFFECT_MODES.ADD,
                value: 1,
                priority: 20
            },
            {
                key: "system.abilities.str.carryMultiplier",
                mode: CONST.ACTIVE_EFFECT_MODES.OVERRIDE,
                value: 2,
                priority: 20
            }
        ]
    };
    return effect;
}

async function createCatsGraceEffect(sourceItem, duration, durationUnit) {
    const effect = {
        label: "Кошачья грация (Enhance Ability)",
        icon: "icons/svg/falling.svg", // Можно заменить на свою иконку
        origin: sourceItem.uuid,
        duration: {
            seconds: convertToSeconds(duration, durationUnit),
            startTime: game.time.worldTime
        },
        flags: {
            core: {
                statusId: "catsGrace"
            },
            dnd5e: {
                effectType: "spell"
            },
            custom: {
                noFallDamage: true
            }
        },
        changes: [
            {
                key: "flags.dnd5e.advantage.ability.save.dex",
                mode: CONST.ACTIVE_EFFECT_MODES.ADD,
                value: 1,
                priority: 20
            },
            {
                key: "flags.dnd5e.advantage.ability.check.dex",
                mode: CONST.ACTIVE_EFFECT_MODES.ADD,
                value: 1,
                priority: 20
            }
        ]
    };
    return effect;
}

async function createFoxsCunningEffect(sourceItem, duration, durationUnit) {
    const effect = {
        label: "Лисья хитрость (Enhance Ability)",
        icon: "icons/svg/light.svg", // Можно заменить на свою иконку
        origin: sourceItem.uuid,
        duration: {
            seconds: convertToSeconds(duration, durationUnit),
            startTime: game.time.worldTime
        },
        flags: {
            core: {
                statusId: "foxsCunning"
            },
            dnd5e: {
                effectType: "spell"
            }
        },
        changes: [
            {
                key: "flags.dnd5e.advantage.ability.save.int",
                mode: CONST.ACTIVE_EFFECT_MODES.ADD,
                value: 1,
                priority: 20
            },
            {
                key: "flags.dnd5e.advantage.ability.check.int",
                mode: CONST.ACTIVE_EFFECT_MODES.ADD,
                value: 1,
                priority: 20
            }
        ]
    };
    return effect;
}

async function createBearsEnduranceEffect(sourceItem, duration, durationUnit, actor) {
    // Бросаем 2d6 для временных хитов
    const tempHP = await new Roll("2d6").roll({async: true});
    const tempHPValue = tempHP.total;

    const effect = {
        label: "Медвежья стойкость (Enhance Ability)",
        icon: "icons/svg/shield.svg", // Можно заменить на свою иконку
        origin: sourceItem.uuid,
        duration: {
            seconds: convertToSeconds(duration, durationUnit),
            startTime: game.time.worldTime
        },
        flags: {
            core: {
                statusId: "bearsEndurance"
            },
            dnd5e: {
                effectType: "spell"
            }
        },
        changes: [
            {
                key: "flags.dnd5e.advantage.ability.save.con",
                mode: CONST.ACTIVE_EFFECT_MODES.ADD,
                value: 1,
                priority: 20
            },
            {
                key: "flags.dnd5e.advantage.ability.check.con",
                mode: CONST.ACTIVE_EFFECT_MODES.ADD,
                value: 1,
                priority: 20
            },
            {
                key: "system.attributes.hp.temp",
                mode: CONST.ACTIVE_EFFECT_MODES.OVERRIDE,
                value: tempHPValue,
                priority: 20
            }
        ]
    };
    return effect;
}

async function createEaglesSplendorEffect(sourceItem, duration, durationUnit) {
    const effect = {
        label: "Орлиное великолепие (Enhance Ability)",
        icon: "icons/svg/aura.svg", // Можно заменить на свою иконку
        origin: sourceItem.uuid,
        duration: {
            seconds: convertToSeconds(duration, durationUnit),
            startTime: game.time.worldTime
        },
        flags: {
            core: {
                statusId: "eaglesSplendor"
            },
            dnd5e: {
                effectType: "spell"
            }
        },
        changes: [
            {
                key: "flags.dnd5e.advantage.ability.save.cha",
                mode: CONST.ACTIVE_EFFECT_MODES.ADD,
                value: 1,
                priority: 20
            },
            {
                key: "flags.dnd5e.advantage.ability.check.cha",
                mode: CONST.ACTIVE_EFFECT_MODES.ADD,
                value: 1,
                priority: 20
            }
        ]
    };
    return effect;
}

async function createOwlsWisdomEffect(sourceItem, duration, durationUnit) {
    const effect = {
        label: "Совиная мудрость (Enhance Ability)",
        icon: "icons/svg/eye.svg", // Можно заменить на свою иконку
        origin: sourceItem.uuid,
        duration: {
            seconds: convertToSeconds(duration, durationUnit),
            startTime: game.time.worldTime
        },
        flags: {
            core: {
                statusId: "owlsWisdom"
            },
            dnd5e: {
                effectType: "spell"
            }
        },
        changes: [
            {
                key: "flags.dnd5e.advantage.ability.save.wis",
                mode: CONST.ACTIVE_EFFECT_MODES.ADD,
                value: 1,
                priority: 20
            },
            {
                key: "flags.dnd5e.advantage.ability.check.wis",
                mode: CONST.ACTIVE_EFFECT_MODES.ADD,
                value: 1,
                priority: 20
            }
        ]
    };
    return effect;
}

// Вспомогательные функции
function convertToSeconds(duration, unit) {
    if (duration === 0) return 0; // Мгновенный эффект

    switch(unit.toLowerCase()) {
        case "round":
            return duration * 6;
        case "minute":
            return duration * 60;
        case "hour":
            return duration * 3600;
        case "day":
            return duration * 86400;
        default:
            return duration;
    }
}

function getEffectName(choice) {
    const names = {
        'bullsStrength': 'Бычья сила',
        'catsGrace': 'Кошачья грация',
        'foxsCunning': 'Лисья хитрость',
        'bearsEndurance': 'Медвежья стойкость',
        'eaglesSplendor': 'Орлиное великолепие',
        'owlsWisdom': 'Совиная мудрость'
    };
    return names[choice] || choice;
}