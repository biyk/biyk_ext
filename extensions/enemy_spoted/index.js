export function init() {
    // ============================================================
    // [MODULE] Обнаружение игрока враждебными NPC при движении (updateToken)
    // ============================================================

    const lastCheckTime = new Map(); // троттлинг для каждого игрока
    let isProcessing = false;        // защита от рекурсии

    // Используем updateToken (срабатывает после обновления документа)
    Hooks.on("updateToken", async (tokenDoc, updateData, options, userId) => {
        console.info("[Detection] updateToken");
        const isDM = () => game.user.isGM;
        if (!isDM()) return;

        // 1. Проверяем, изменилась ли позиция (x или y)
        if (updateData.x === undefined && updateData.y === undefined) return console.info("[Detection] updateData");;

        // 2. Получаем объект токена на сцене
        const token = canvas.tokens.get(tokenDoc.id);
        if (!token) return console.info("[Detection] token");
        const actor = token.actor;
        if (!actor?.hasPlayerOwner) return  console.info("[Detection] hasPlayerOwner");

        // 3. Движение инициировано самим игроком (не GM и не другим пользователем)
        const user = game.users.get(userId);
        if (!user || user.isGM) return  console.info("[Detection] isGM");;;

        console.info("[Detection] Игрок переместился, запускаем проверку");

        // 4. Троттлинг – не чаще 1 раза в секунду
        const now = Date.now();
        const last = lastCheckTime.get(user.id) || 0;
        if (now - last < 1000) return;
        lastCheckTime.set(user.id, now);

        // 5. Защита от параллельной обработки
        if (isProcessing) return;
        isProcessing = true;
        try {
            await checkPlayerDetection(token);
        } finally {
            isProcessing = false;
        }
    });

    // ---- ВСЕ ОСТАЛЬНЫЕ ФУНКЦИИ (checkPlayerDetection, checkLineOfSight, startCombat) ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ ----
    // Они такие же, как в вашем коде. Приведу их для полноты:

    async function checkPlayerDetection(playerToken) {
        console.log(`[Detection] Проверка обнаружения для игрока ${playerToken.name}`);

        const playerActor = playerToken.actor;
        const stealthBonus = playerActor.system.skills?.ste?.total ?? playerActor.system.skills?.ste?.mod ?? 0;
        console.log(`[Detection] Бонус скрытности ${playerToken.name}: ${stealthBonus}`);

        const currentCombat = game.combat;
        const existingCombatantIds = currentCombat ? new Set(currentCombat.combatants.map(c => c.tokenId)) : new Set();
        const radiusFeet = 60;
        const radiusPx = (radiusFeet / 5) * canvas.grid.size;

        const nearbyNPCs = [];
        for (let npcToken of canvas.tokens.placeables) {
            if (npcToken.id === playerToken.id) continue;
            const npcActor = npcToken.actor;
            if (!npcActor || npcActor.type !== 'npc') continue;
            if (npcActor.system.attributes.hp.value <= 0) continue;
            if (npcToken.document.disposition !== -1) continue;
            if (currentCombat && existingCombatantIds.has(npcToken.id)) continue;

            const dist = Math.hypot(npcToken.center.x - playerToken.center.x, npcToken.center.y - playerToken.center.y);
            if (dist > radiusPx) continue;

            const distanceFeet = (dist / canvas.grid.size) * 5;
            let hasLOS = false;
            if (distanceFeet < 10) {
                hasLOS = true;
            } else {
                hasLOS = await checkLineOfSight(npcToken.center, playerToken.center);
            }
            if (!hasLOS) continue;
            nearbyNPCs.push(npcToken);
        }

        if (nearbyNPCs.length === 0) {
            console.log(`[Detection] Рядом с ${playerToken.name} нет враждебных NPC`);
            return;
        }

        const detectedNPCs = [];
        for (let npcToken of nearbyNPCs) {
            const perceptionBonus = npcToken.actor.system.skills?.prc?.total ?? npcToken.actor.system.skills?.prc?.mod ?? npcToken.actor.system.abilities.wis.mod;
            const playerRoll = await new Roll(`1d20 + ${stealthBonus}`).evaluate();
            const npcRoll = await new Roll(`1d20 + ${perceptionBonus}`).evaluate();
            console.log(`[Detection] ${npcToken.name} (${npcRoll.total}) vs ${playerToken.name} (${playerRoll.total})`);
            if (npcRoll.total >= playerRoll.total) {
                detectedNPCs.push(npcToken);
                console.log(`[Detection] ✅ ${npcToken.name} заметил ${playerToken.name}`);
            } else {
                console.log(`[Detection] ❌ ${npcToken.name} не заметил`);
            }
        }

        if (detectedNPCs.length === 0) return;

        const npcNames = detectedNPCs.map(n => n.name).join(", ");
        const dialogResult = await Dialog.confirm({
            title: "⚠️ Обнаружение игрока!",
            content: `<p><strong>${playerToken.name}</strong> замечен: ${npcNames}</p><p>Начать бой? (Будут добавлены все игроки на сцене и эти NPC)</p>`,
            yes: () => true,
            no: () => false
        });
        if (!dialogResult) return;

        const allPlayers = canvas.tokens.placeables.filter(t => t.actor?.hasPlayerOwner === true);
        const allDetectedNPCs = new Set(detectedNPCs);
        await startCombat(allPlayers, Array.from(allDetectedNPCs));
    }

    async function checkLineOfSight(pointA, pointB) {
        try {
            const ray = new Ray(pointA, pointB);
            const collision = canvas.walls.checkCollision(ray, { type: "sight", mode: "any" });
            return !collision;
        } catch (err) {
            console.warn("[Detection] Ошибка LOS:", err);
            return true;
        }
    }

    async function startCombat(playerTokens, npcTokens) {
        const scene = canvas.scene;
        if (!scene) return;

        let combat = game.combat;
        if (!combat || combat.scene?.id !== scene.id) {
            combat = await Combat.create({ scene: scene.id });
        }

        const existingIds = new Set(combat.combatants.map(c => c.tokenId));
        const toAdd = [];
        for (let pt of playerTokens) if (!existingIds.has(pt.id)) toAdd.push({ tokenId: pt.id, sceneId: scene.id });
        for (let npc of npcTokens) if (!existingIds.has(npc.id)) toAdd.push({ tokenId: npc.id, sceneId: scene.id });

        // Добавляем участников стандартным способом (не вызывает ошибок combat-tracker-dock)
        if (toAdd.length) {
            await combat.createEmbeddedDocuments("Combatant", toAdd);
            // Принудительное обновление трекера — теперь токены появятся визуально
            if (ui.combat) ui.combat.render();
        }

        // Бой не начинаем, оставляем его в состоянии "готовности"

        ChatMessage.create({
            content: `<strong>⚔️ Токены добавлены в инициативу (бой не начат)!</strong><br>Игроки: ${playerTokens.map(t=>t.name).join(", ")}<br>Враги: ${npcTokens.map(t=>t.name).join(", ")}`,
            whisper: game.users.filter(u=>u.isGM).map(u=>u.id)
        });
    }
}