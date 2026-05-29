/**
 * Возвращает для токена количество шагов в 8 направлениях до препятствия.
 * @param {Token} token - объект токена на сцене
 * @returns {Promise<Object>} { up, upRight, right, downRight, down, downLeft, left, upLeft } – число шагов (целые)
 */
export async function getMovementRose(token) {
    if (!token) return null;

    // === Вспомогательная функция проверки возможности перемещения ===
    async function canMoveTo(x, y) {
        // 1. Через TokenDocument.checkCollision (Foundry V10+)
        if (typeof token.document?.checkCollision === "function") {
            return await token.document.checkCollision(x, y, { mode: "move" });
        }
        // 2. Через CONFIG.Canvas.polygonBackends.movement (V11+)
        const movementBackend = CONFIG.Canvas.polygonBackends?.movement;
        if (movementBackend && typeof movementBackend.testCollision === "function") {
            const newBounds = new PIXI.Rectangle(x, y, token.w, token.h);
            const collision = movementBackend.testCollision({
                type: "movement",
                object: token,
                source: newBounds,
                mode: "any"
            });
            return !collision;
        }
        // 3. Fallback (работает, но может быть устаревшим)
        if (canvas.walls?.checkCollision) {
            const ray = new Ray(token.center, { x: x + token.w / 2, y: y + token.h / 2 });
            const collision = canvas.walls.checkCollision(ray, { type: "move", mode: "any", object: token });
            return !collision;
        }
        console.warn("getMovementRose: нет метода проверки коллизий, разрешаем движение");
        return true;
    }

    // === Настройки ===
    const step = canvas.grid.size;          // размер клетки в пикселях
    const directions = [
        { name: "up",        dx: 0,  dy: -step },
        { name: "upRight",   dx: step, dy: -step },
        { name: "right",     dx: step, dy: 0 },
        { name: "downRight", dx: step, dy: step },
        { name: "down",      dx: 0,  dy: step },
        { name: "downLeft",  dx: -step, dy: step },
        { name: "left",      dx: -step, dy: 0 },
        { name: "upLeft",    dx: -step, dy: -step }
    ];

    const result = {};

    // Для каждого направления считаем шаги
    for (const dir of directions) {
        let steps = 0;
        let curX = token.x;
        let curY = token.y;
        let blocked = false;

        while (!blocked) {
            const newX = curX + dir.dx;
            const newY = curY + dir.dy;

            // Проверка границ сцены
            if (newX < 0 || newY < 0 || newX > canvas.dimensions.width || newY > canvas.dimensions.height) {
                blocked = true;
                break;
            }

            const moveAllowed = await canMoveTo(newX, newY);
            if (moveAllowed) {
                steps++;
                curX = newX;
                curY = newY;
            } else {
                blocked = true;
            }
        }
        result[dir.name] = steps;
    }
    return result;
}