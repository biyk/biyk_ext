// Data\modules\biyk_ext\settings.js
Hooks.once('init', () => {
    const choices = {                
      'currency-watcher': 'Currency Watcher',
      'sanctuary': 'Sanctuary',
      'warlord_word' : 'Вдохновляющее слово',
      'warlord_help' : 'Лидер - Наставник',
      'activate_effect' :" Активация эффектов при активации заклинаний",
      'Indefatigable_endurance' : 'Неутомимая выносливость',
      'ArcaneRecovery' : 'Магическое восстановление'
    };

    for (let key in choices){
        game.settings.register('biyk_ext', key, { // используем key как уникальный идентификатор
            name: choices[key],  // отображаемое имя
            hint: `Enable ${choices[key]}`, // подсказка
            scope: "world",
            config: true,          // чтобы было видно в стандартном окне настроек
            default: false,
            requiresReload: true,
            type: Boolean,
        });
    }
});
