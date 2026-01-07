export function init() {
    Hooks.on("dnd5e.useItem", async (item, config, options) => {
        if (item.name.toLowerCase().includes('protection from poison')) {
            for(let effect of game.user.targets.first().actor.effects){
                if (effect.name.toLowerCase()=='poisoned') return await effect.delete();
            }
        }
    });
}
