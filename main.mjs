// Data\modules\biyk_ext\main.js

import { EXTENSIONS } from './registry.js';

Hooks.once('init', async () => {
    console.log("biyk_ext | init");

    game.biyk_ext = {
        extensions: {},
        async loadExtensions() {
            // Получаем все ключи настроек, которые соответствуют включённым расширениям
            const enabledSettings = Object.keys(EXTENSIONS).filter(key => game.settings.get('biyk_ext', key));

            console.log("Включённые расширения:", enabledSettings);

            // Загружаем и инициализируем расширения
            for (const ext of enabledSettings) {
                if (!game.biyk_ext.extensions[ext]) {
                    try {
                        const mod = await import(`./extensions/${ext}/index.js`);
                        game.biyk_ext.extensions[ext] = mod;
                        mod.init?.();
                        console.log(`biyk_ext | ${ext} | init`);
                    } catch (e) {
                        console.error(`biyk_ext | Не удалось загрузить расширение: ${ext}`, e);
                    }
                }
            }
        }
    };
});

Hooks.once('ready', async () => {
    await game.biyk_ext.loadExtensions();
});
