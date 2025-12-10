// Data\modules\biyk_ext\main.js
Hooks.once('init', async () => {
  console.log("biyk_ext | init");

  game.biyk_ext = {
    extensions: {},
    async loadExtensions() {
      // Получаем все настройки расширений
      const enabledSettings = [
        'currency-watcher', 
        'sanctuary', 
        'warlord_word', 
        'warlord_help', 
        'activate_effect', 
        'Indefatigable_endurance',
        'ArcaneRecovery'
      ]; // ключи твоих настроек

      // Фильтруем только включённые
      const enabledExtensions = enabledSettings.filter(key => game.settings.get('biyk_ext', key));

      console.log("Включённые расширения:", enabledExtensions);

      // Затем можно загружать их как раньше
      for (const ext of enabledExtensions) {
        if (!game.biyk_ext.extensions[ext]) {
          try {
            const mod = await import(`./extensions/${ext}/index.js`);
            game.biyk_ext.extensions[ext] = mod;
            mod.init?.();
            console.log(`biyk_ext | ${ext} |init`);
          } catch (e) {
            console.error(`biyk_ext | Failed to load extension: ${ext}`, e);
          }
        }
      }

    }
  };
});

Hooks.once('ready', async () => {
  await game.biyk_ext.loadExtensions();
});
