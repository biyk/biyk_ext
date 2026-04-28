//К примеру, вы хотите «проигнорировать» обычный вызов и сами инициировать событие на стороне GM
// (например, после того как игрок что-то сделал). Тогда вы можете отправить сокет-сообщение от игрока к DM:

// На клиенте игрока
game.socket?.emit("myModule.triggerCombatTurn", combat.id, combatant.id);


// На клиенте GM (заранее подписаться)
game.socket?.on("myModule.triggerCombatTurn", async (combatId, combatantId) => {
    const combat = game.combats.get(combatId);
    const combatant = combat?.combatants.get(combatantId);
    if (combat && combatant) {
        await Hooks.callAll("combatTurn", combat, combatant);
    }
});