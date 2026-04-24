export async function target(token, conf) {
    if (!token) return ui.notifications.warn("Выбери токен");
    const sel = document.querySelector('#polyglot select');
    if (!sel) return ui.notifications.error("Polyglot не найден");
    const prev = sel.value;
    sel.value = conf.lang = "draconic";
    sel.dispatchEvent(new Event('change', {bubbles: true}));
    await ChatMessage.create({
        speaker: {token: token.document, actor: token.actor, scene: canvas.scene},
        content: "я - кобольд!",
        type: CONST.CHAT_MESSAGE_TYPES.IC
    });
    sel.value = prev;
    sel.dispatchEvent(new Event('change', {bubbles: true}));
};