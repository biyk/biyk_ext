export function init() {
    Hooks.on("dnd5e.useItem", async (item, config, options) => {
        if (item.name.toLowerCase().includes('lesser restoration')) {
            for(let effect of game.user.targets.first().actor.effects){
                if (effect.name.toLowerCase()=='poisoned') return await effect.delete();
                if (effect.name.toLowerCase()=='paralyzed') return await effect.delete();
                if (effect.name.toLowerCase()=='deafened') return await effect.delete();
                if (effect.name.toLowerCase()=='blinded') return await effect.delete();
            }
        }


    });
}
