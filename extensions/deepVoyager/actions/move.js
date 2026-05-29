/**
 * Перемещает токен с проверкой коллизий (стены, двери, препятствия)
 * @param {Token} token - объект токена
 * @param {Object} conf - { direction: "up"/"down"/"left"/"right" }
 * @returns {Promise<boolean>}
 */
import {log} from "../utils/logger.js";

export async function move(token = null, conf) {
    if (!token) {
        ui.notifications.warn("Токен не передан");
        return "Токен не передан";
    }


    const step = canvas.grid.size;
    const direction = conf.direction;
    let dx = 0, dy = 0;
    const movementBackend = CONFIG.Canvas.polygonBackends?.movement;

    // === ОПЦИОНАЛЬНЫЙ ВЫВОД: максимальные шаги до препятствия (8 направлений) ===
// === ОПЦИОНАЛЬНЫЙ ВЫВОД: расстояние в пикселях от центра токена до препятствия (8 направлений) ===
    if (conf.debug === true) {
        const dirs = ["up", "down", "left", "right", "upleft", "upright", "downleft", "downright"];
        // Векторы направлений из центра (единичные, в пикселях)
        const vectors = {
            up:       { dx: 0,  dy: -1 },
            down:     { dx: 0,  dy:  1 },
            left:     { dx: -1, dy:  0 },
            right:    { dx:  1, dy:  0 },
            upleft:   { dx: -1, dy: -1 },
            upright:  { dx:  1, dy: -1 },
            downleft: { dx: -1, dy:  1 },
            downright:{ dx:  1, dy:  1 }
        };
        const start = token.center;
        const distances = {};

        for (const dir of dirs) {
            const vec = vectors[dir];
            // Нормализуем вектор (диагональный делим на sqrt(2), чтобы шаг был 1 пиксель и точность)
            let len = Math.hypot(vec.dx, vec.dy);
            let stepX = vec.dx / len;
            let stepY = vec.dy / len;
            let currentX = start.x;
            let currentY = start.y;
            let distance = 0;
            let blocked = false;
            const maxDistance = Math.max(canvas.dimensions.width, canvas.dimensions.height) * 2; // ограничитель

            while (!blocked && distance < maxDistance) {
                // Делаем маленький шаг (1 пиксель)
                currentX += stepX;
                currentY += stepY;
                distance++;
                // Теперь нужно проверить, не пересекает ли токен (с его размерами) какую-либо стену или другой токен
                // Для этого построим границы токена с центром в (currentX, currentY)
                const left = currentX - token.w/2;
                const top = currentY - token.h/2;
                const bounds = new PIXI.Rectangle(left, top, token.w, token.h);

                // Проверка границ сцены
                if (left < 0 || top < 0 || left + token.w > canvas.dimensions.width || top + token.h > canvas.dimensions.height) {
                    blocked = true;
                    break;
                }

                // Проверка коллизии со стенами
                let collision = false;
                const movementBackend = CONFIG.Canvas.polygonBackends?.movement;
                if (movementBackend && typeof movementBackend.testCollision === "function") {
                    try {
                        collision = movementBackend.testCollision({
                            type: "movement",
                            object: token,
                            source: bounds,
                            mode: "any"
                        });
                    } catch(e) { collision = true; }
                } else if (typeof token.document?.checkCollision === "function") {
                    // Для checkCollision нужны координаты левого верхнего угла
                    collision = !(await token.document.checkCollision(left, top, { mode: "move" }));
                } else if (canvas.walls?.checkCollision) {
                    const ray = new Ray(token.center, { x: currentX, y: currentY });
                    collision = canvas.walls.checkCollision(ray, { type: "move", mode: "any", object: token });
                } else {
                    collision = false;
                }
                if (collision) {
                    blocked = true;
                    break;
                }

                // Проверка другого живого токена (пересечение прямоугольников)
                const occupied = canvas.tokens.placeables.some(t =>
                    t.id !== token.id &&
                    (t.actor?.system?.attributes?.hp?.value ?? 0) > 0 &&
                    t.x < left + token.w && t.x + t.w > left &&
                    t.y < top + token.h && t.y + t.h > top
                );
                if (occupied) {
                    blocked = true;
                    break;
                }
            }
            distances[dir] = distance; // в пикселях (евклидово расстояние от центра до препятствия)
        }
        log.info(`[DEBUG] Расстояние от центра до препятствия (пиксели) для ${token.name}: ` +
            `up=${distances.up}, down=${distances.down}, left=${distances.left}, right=${distances.right}, ` +
            `upleft=${distances.upleft}, upright=${distances.upright}, downleft=${distances.downleft}, downright=${distances.downright}`);
    }

    // --- Расчёт смещения ---
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
            log.warn("неизвестное направление", direction);
            return "неизвестное направление";
    }

    const newX = token.x + dx;
    const newY = token.y + dy;
    const newBounds = new PIXI.Rectangle(newX, newY, token.w, token.h);

    // --- Проверка занятости живыми токенами (пересечение bounding box) ---
    const occupiedByOther = canvas.tokens.placeables.some(t =>
        t.id !== token.id && 
        (t.actor?.system?.attributes?.hp?.value ?? 0) > 0 &&
        t.x < newBounds.x + newBounds.width &&
        t.x + t.w > newBounds.x &&
        t.y < newBounds.y + newBounds.height &&
        t.y + t.h > newBounds.y
    );

    if (occupiedByOther) {
        const occupier = canvas.tokens.placeables.find(t =>
            t.id !== token.id &&
            (t.actor?.system?.attributes?.hp?.value ?? 0) > 0 &&
            t.x < newBounds.x + newBounds.width &&
            t.x + t.w > newBounds.x &&
            t.y < newBounds.y + newBounds.height &&
            t.y + t.h > newBounds.y
    );
        log.info(`move: клетка занята живым ${occupier?.name}`);
        return `move: клетка занята живым ${occupier?.name} (${newX}, ${newY})`;
    }

    // --- Проверка столкновений (современный API V11+) ---
    let movementAllowed = false;

    // 1. Приоритет: CONFIG.Canvas.polygonBackends.movement
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
            log.warn("Ошибка при modern collision check:", err);
        }
    }

    // 2. Fallback: token.document.checkCollision (может не учитывать размер, но оставляем)
    if (!movementAllowed && movementAllowed !== false && typeof token.document?.checkCollision === "function") {
        movementAllowed = await token.document.checkCollision(newX, newY, { mode: "move" });
    }

    // 3. Старый fallback (на случай совсем старых версий)
    if (!movementAllowed && canvas.walls?.checkCollision) {
        const newCenter = { x: newX + token.w/2, y: newY + token.h/2 };
        const ray = new Ray(token.center, newCenter);
        movementAllowed = !canvas.walls.checkCollision(ray, { type: "move", mode: "any", object: token });
    }

    // Если ни один метод не сработал, выдаём ошибку
    if (!movementAllowed && movementAllowed !== false) {
        return "Нет метода проверки столкновений";
    }

    if (!movementAllowed) {
        return `Путь заблокирован! ${token.name} не может пройти в (${newX}, ${newY}).`;
    }

    // Перемещаем с анимацией
    await token.document.update({ x: newX, y: newY }, { animate: true });
    await new Promise(resolve => setTimeout(resolve, 500)); // синхронизация



    return true;
}