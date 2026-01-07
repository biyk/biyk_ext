// Data\modules\biyk_ext\settings.mjs
import { EXTENSIONS } from './registry.js';

Hooks.once('init', () => {
    // Динамически создаем настройки для каждого расширения из EXTENSIONS
    for (let key in EXTENSIONS) {
        const extension = EXTENSIONS[key];

        // Регистрируем настройку для каждого расширения
        game.settings.register('biyk_ext', key, {
            name: extension.label, // Отображаемое имя расширения
            hint: `Enable ${extension.label}`, // Подсказка
            scope: "world",
            config: true,           // Чтобы оно было видно в стандартном окне настроек
            default: false,         // Значение по умолчанию
            requiresReload: extension.reload, // Если нужно перезагрузить, указываем значение из регистра
            type: Boolean,          // Тип данных (булево значение)
        });
    }

    // Логирование информации для отладки
    console.log("biyk_ext | EXTENSIONS", EXTENSIONS);
});
