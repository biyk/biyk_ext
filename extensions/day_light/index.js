export function init() {

    Hooks.on("simple-calendar-date-time-change", (data) => {
        
    if (!game.user.isGM) {
       return
    }

        let hour = data.date.hour

        const scene = game.scenes.active; // текущая сцена

        if (!scene.globalLight) return;
        let darkness = 0.0;
        if (hour>=0 && hour < 12) {
            darkness = 1-(hour/12).toFixed(2);
            scene.update({ globalLight: true, darkness: darkness });
        }
        else {
            darkness = ((hour-12)/12).toFixed(2);
            scene.update({ globalLight: true, darkness: darkness });
        }


    });


}
