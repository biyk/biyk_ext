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

                // Проверка другого живого токена (пересечение прямоугольников) — по документам,
                // чтобы расхождение canvas/документ не рисовало фантомных соседей.
                const occupied = canvas.tokens.placeables.some(t =>
                    t.id !== token.id &&
                    (t.actor?.system?.attributes?.hp?.value ?? 0) > 0 &&
                    t.document.x < left + token.w && t.document.x + t.w > left &&
                    t.document.y < top + token.h && t.document.y + t.h > top
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

    // --- Координаты: источник истины — документ токена ---
    // Canvas-позиция (token.x/y) в Foundry 11 проставляется только при сбросе render-флагов,
    // поэтому каждый шаг одного хода считался от одной и той же устаревшей точки: 5 шагов
    // политики превращались в 1 реальную клетку, а токен мог «телепортироваться» назад.
    // ВАЖНО: Foundry хранит точные координаты, которые могут "плыть" после нескольких update().
    // Принудительно округляем до сетки перед каждым шагом, чтобы избежать накопления ошибки.
    const baseX = Math.round(token.document.x / step) * step;
    const baseY = Math.round(token.document.y / step) * step;
    log.info(`move ${token.name}: START base=(${baseX},${baseY}) dir=${direction} dx=${dx} dy=${dy}`);
    const newX = baseX + dx;
    const newY = baseY + dy;
    const newBounds = new PIXI.Rectangle(newX, newY, token.w, token.h);

    // --- Проверка границ сцены (о них checkCollision ничего не знает) ---
    if (newX < 0 || newY < 0 || newX + token.w > canvas.dimensions.width
        || newY + token.h > canvas.dimensions.height) {
        return `Путь заблокирован! ${token.name} выходит за границу сцены (${newX}, ${newY}).`;
    }

    // --- Проверка занятости живыми токенами (пересечение bounding box) ---
    // Соседей берём из документов: их token.x/y тоже может отставать на клетку.
    const isOccupiedBy = t =>
        t.id !== token.id &&
        (t.actor?.system?.attributes?.hp?.value ?? 0) > 0 &&
        t.document.x < newBounds.x + newBounds.width &&
        t.document.x + t.w > newBounds.x &&
        t.document.y < newBounds.y + newBounds.height &&
        t.document.y + t.h > newBounds.y;

    if (canvas.tokens.placeables.some(isOccupiedBy)) {
        const occupier = canvas.tokens.placeables.find(isOccupiedBy);
        log.info(`move: клетка занята живым ${occupier?.name}`);
        return `move: клетка занята живым ${occupier?.name} (${newX}, ${newY})`;
    }

    // --- Проверка столкновений ---
    // В Foundry 11 нет CONFIG.Canvas.polygonBackends.movement (ключи: sight, light, sound, move)
    // и нет TokenDocument#checkCollision — прежние ветки 1 и 2 никогда не выполнялись.
    // Ray строим центр-в-центр: старый вариант шёл от token.center в (newX + w/2), то есть
    // с перелётом на полклетки, что давало ложные блокировки проходов.
    let movementAllowed = null;
    if (canvas.walls?.checkCollision) {
        const from = { x: baseX + token.w / 2, y: baseY + token.h / 2 };
        const to = { x: newX + token.w / 2, y: newY + token.h / 2 };
        movementAllowed = !canvas.walls.checkCollision(
            new Ray(from, to), { type: "move", mode: "any", object: token });
    }

    if (movementAllowed === null) {
        return "Нет метода проверки столкновений";
    }

    if (!movementAllowed) {
        return `Путь заблокирован! ${token.name} не может пройти в (${newX}, ${newY}).`;
    }

    // Перемещаем и сразу синхронизируем PIXI-позицию: следующий шаг того же хода (и любой,
    // кто читает token.x/y) обязан видеть новые координаты, а не устаревшие.
    log.info(`move ${token.name}: BEFORE doc=(${token.document.x},${token.document.y}) canvas=(${token.x},${token.y}) dir=${direction}`);
    await token.document.update({ x: newX, y: newY }, { animate: true });
    // Foundry 11: после update() canvas position отстаёт до следующего render cycle.
    // Читаем актуальные координаты из документа, а не вычисляем сами — это гарантирует
    // точное совпадение с сеткой независимо от внутренних snap-алгоритмов Foundry.
    const docPos = { x: token.document.x, y: token.document.y };
    token.position.set(docPos.x, docPos.y);
    log.info(`move ${token.name}: AFTER doc=(${docPos.x},${docPos.y}) canvas=(${token.x},${token.y}) expected=(${newX},${newY})`);
    await new Promise(resolve => setTimeout(resolve, 600)); // синхронизация

    return true;
}