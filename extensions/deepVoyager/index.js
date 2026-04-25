import {move} from "./actions/move.js";
import {target} from "./actions/target.js";
import {use} from "./actions/use.js";
import {getAction} from "./actions/api.js";
import {sendMessage} from "./actions/message.js";
import {getStatus, buildItemAction} from "./utils/help.js";

export function init() {

    let getSpeed = actor => actor?.system?.attributes?.movement?.walk || 0;

    const isDM = () => game.user.isGM;

     async function combatTurn() {
         if (!isDM()) return;
         await new Promise(resolve => setTimeout(resolve, 500)); // синхронизация

         let token = canvas.tokens.objects.children.filter(token => token.id === game.combat.current.tokenId)[0];
         if (!token) return console.log('no tokens');

         console.log(token);
         if (token.actor?.system?.attributes?.hp == 0) return console.log('Актер мертв');
         if (token.actor?.type !== 'npc') return console.log('это не НПС');
         let data = {};
         data.name = token.name;
         data.x = token.x;
         data.y = token.y;
         data.speed = getSpeed(token.actor);
         data.step = canvas.grid.size;
         data.baseMove =  data.speed / 5;
         data.status = getStatus(token.actor);

         const languagesSet = token.actor?.system?.traits?.languages?.value;
         const languages = languagesSet ? [...languagesSet].join(", ") : "common";
         data.languages = languages;

         data.disposition = token.document?.disposition ?? 0;

         // ---------- 1. Персонажи, которых видит токен ----------
         const visibleTokens = [];
         for (let otherToken of canvas.tokens.placeables) {
             if (otherToken.id === token.id) continue;

             let hasLineOfSight = false;
             try {
                 const sightBackend = CONFIG.Canvas.polygonBackends?.sight;
                 if (sightBackend && typeof sightBackend.testCollision === "function") {
                     const collision = sightBackend.testCollision({
                         type: "sight",
                         source: token.center,
                         destination: otherToken.center,
                         mode: "any"
                     });
                     hasLineOfSight = !collision;
                 } else {
                     // Старый метод как fallback
                     const ray = new Ray(token.center, otherToken.center);
                     const collision = canvas.walls.checkCollision(ray, {type: "sight", mode: "any"});
                     hasLineOfSight = !collision;
                 }
             } catch (e) {
                 console.warn(`Ошибка проверки видимости для ${otherToken.name}:`, e);
                 hasLineOfSight = true;
             }

             if (!hasLineOfSight) continue;

             const actorData = otherToken.actor;
             if (!actorData) continue;

             //TODO оружия в руках может быть два
             let equippedWeapon = null;
             const weapon = actorData.items.find(i => i.type === "weapon" && i.system.equipped);
             if (weapon) equippedWeapon = {name: weapon.name, id: weapon.id};

             const ac = actorData.system.attributes.ac?.value || 10;

             const status = getStatus(actorData);

             visibleTokens.push({
                 id: otherToken.id,
                 name: otherToken.name,
                 disposition: otherToken.document?.disposition ?? 0,
                 x: otherToken.x,
                 y: otherToken.y,
                 weapon: equippedWeapon,
                 ac: ac,
                 status: status
             });
         }

         // Группировка по отношению к текущему токену
         const currentDisposition = token.document?.disposition ?? 0;
         const friends = [];
         const enemies = [];
         const neutrals = [];

         for (const t of visibleTokens) {
             if (t.disposition === 0) {
                 neutrals.push(t);
             } else if (t.disposition === currentDisposition) {
                 friends.push(t);
             } else {
                 enemies.push(t);
             }
         }

         data.visibleTokens = visibleTokens;   // общий список (опционально)
         data.friends = friends;
         data.enemies = enemies;
         data.neutrals = neutrals;

         // ---------- 2. Доступные действия (способности) ----------
         const availableActions = [];
         for (let item of token.actor.items) {
             // Типы предметов, которые могут быть использованы в бою
             if (item.type === "weapon" || item.type === "spell" || item.type === "feat" || item.type === "consumable") {
                 availableActions.push(buildItemAction(item));
             }
         }
         // Можно отсортировать по значимости (оружие ближнего боя, затем заклинания)
         availableActions.sort((a, b) => (a.type === "weapon" && b.type !== "weapon") ? -1 : 1);
         data.availableActions = availableActions;

         // ---------- 3. Передаём данные нейросети ----------

         console.log(data);
         let actions = await getAction(data);


         let limit = {
             move: data.baseMove,
             use: 1,
             bonus: 1,
             target: 1
         }
         for (const item of actions) {
             let action = item.action;
             let conf = item.conf;

             // Выполняем действия
             if (action === 'move') {
                 await move(token, conf);
             }
             if (action === 'target') {
                 target(token, conf);
             }
             if (action === 'use') {
                 await use(token, conf);
             }
             if (action === 'message') {
                 await sendMessage(token, conf);
             }
         }
         ui.notifications.warn(`Ход завершен!`);
         game.combat.nextTurn();
     }

    // === Хуки ===
    Hooks.on("combatTurn", async (combat, combatant) => {
        await combatTurn()
    });
     Hooks.on("combatRound", async (combat, combatant) => {
       await combatTurn()
    });
}