/**
 * Возвращает для токена количество шагов в 8 направлениях до препятствия.
 * @param {Token} token - объект токена на сцене
 * @returns {Promise<Object>} { up, upRight, right, downRight, down, downLeft, left, upLeft } – число шагов (целые)
 */
export async function getMovementRose(token) {
    if (!token) return null;

    // === Вспомогательная функция проверки возможности перемещения ===
    // fromX/fromY — центр ТЕКУЩЕЙ клетки пути: ray обязан идти центр-в-центр конкретного шага,
    // иначе после первого шага проверяется не то направление (старый вариант всегда начинал
    // луч от token.center). В Foundry 11 нет ни TokenDocument#checkCollision, ни
    // polygonBackends.movement — рабочий способ один: canvas.walls.checkCollision.
    async function canMoveTo(x, y, fromX, fromY) {
        if (canvas.walls?.checkCollision) {
            const ray = new Ray({ x: fromX, y: fromY }, { x: x + token.w / 2, y: y + token.h / 2 });
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
        // Координаты — из документа: canvas-позиция может отставать до сброса render-флагов.
        let curX = token.document.x;
        let curY = token.document.y;
        let blocked = false;

        while (!blocked) {
            const newX = curX + dir.dx;
            const newY = curY + dir.dy;

            // Проверка границ сцены
            if (newX < 0 || newY < 0 || newX > canvas.dimensions.width || newY > canvas.dimensions.height) {
                blocked = true;
                break;
            }

            const moveAllowed = await canMoveTo(newX, newY, curX + token.w / 2, curY + token.h / 2);
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