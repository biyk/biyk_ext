/**
 * Перемещает токен с проверкой коллизий (стены, двери, препятствия)
 * @param {Token} token - объект токена
 * @param {Object} conf - { direction: "up"/"down"/"left"/"right" }
 * @returns {Promise<boolean>}
 */
export async function move(token = null, conf) {
    if (!token) {
        ui.notifications.warn("Токен не передан");
        return false;
    }

    const step = canvas.grid.size;
    const direction = conf.direction;
    let dx = 0, dy = 0;

    switch (direction) {
        case "up":    dy = -step; break;
        case "down":  dy =  step; break;
        case "left":  dx = -step; break;
        case "right": dx =  step; break;
        case "upleft":    dx = -step; dy = -step; break;
        case "upright":   dx =  step; dy = -step; break;
        case "downleft":  dx = -step; dy =  step; break;
        case "downright": dx =  step; dy =  step; break;
        default:
            console.warn("move: неизвестное направление", direction);
            return false;
    }

    const newX = token.x + dx;
    const newY = token.y + dy;

    // --- Проверка: занят ли целевой токен (только живой) ---
    const occupiedToken = canvas.tokens.placeables.find(t => 
        t.id !== token.id && 
        t.x === newX && 
        t.y === newY &&
        (t.actor?.system?.attributes?.hp?.value ?? 0) > 0
    );
    if (occupiedToken) {
        console.log(`move: клетка занята живым ${occupiedToken.name}`);
        return false;
    }

    // --- Проверка столкновений (современный API V11+) ---
    let movementAllowed = false;

    // 1. Приоритет: CONFIG.Canvas.polygonBackends.movement
    const movementBackend = CONFIG.Canvas.polygonBackends?.movement;
    if (movementBackend && typeof movementBackend.testCollision === "function") {
        try {
            const newBounds = new PIXI.Rectangle(newX, newY, token.w, token.h);
            const collision = movementBackend.testCollision({
                type: "movement",
                object: token,
                source: newBounds,
                mode: "any"
            });
            movementAllowed = !collision;
        } catch (err) {
            console.warn("Ошибка при modern collision check:", err);
        }
    }

    // 2. Второй метод: token.document.checkCollision (если предыдущий не дал ответа)
    if (!movementAllowed && typeof token.document.checkCollision === "function") {
        movementAllowed = await token.document.checkCollision(newX, newY, { mode: "move" });
    }

    // 3. Третий fallback: старый canvas.walls.checkCollision (на случай совсем старых версий)
    if (!movementAllowed && canvas.walls?.checkCollision) {
        const newCenter = { x: newX + token.w/2, y: newY + token.h/2 };
        const ray = new Ray(token.center, newCenter);
        movementAllowed = !canvas.walls.checkCollision(ray, { type: "move", mode: "any", object: token });
    }

    // Если ни один метод не сработал, выдаём ошибку
    if (!movementAllowed && movementAllowed !== false) {
        //ui.notifications.error("Нет метода проверки столкновений");
        return false;
    }

    if (!movementAllowed) {
        //ui.notifications.warn(`Путь заблокирован! ${token.name} не может пройти.`);
        return false;
    }

    // Перемещаем с анимацией
    await token.document.update({ x: newX, y: newY }, { animate: true });
    await new Promise(resolve => setTimeout(resolve, 500)); // синхронизация
    //ui.notifications.info(`${token.name} переместился на ${step}px ${direction}.`);
    return true;
}