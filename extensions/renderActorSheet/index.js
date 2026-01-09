export function init() {
    Hooks.on("renderActorSheetV2", (app) => {
        // Проверяем, что это именно лист персонажа
        const actor = app.actor;

        if (!actor) {
            console.warn("Лист рендерится без актора");
            return;
        }
        if (game.user.isGM){
            return;
        }

        document.getElementsByClassName('sheet-header-buttons')[0].style.display = 'none'
        document.querySelectorAll('section.currency input,button').forEach(input => {
            input.disabled = true;
        });

    });
}
