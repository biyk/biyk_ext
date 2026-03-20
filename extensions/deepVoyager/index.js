import {move} from "./actions/move.js";
import {target} from "./actions/target.js";
import {use} from "./actions/use.js";
export function init() {

    let getSpeed = actor => actor?.system?.attributes?.movement?.walk || 0;

    const isDM = () => {
        return game.user.isGM;
    };

    // === Хуки ===
    Hooks.on("combatTurn", async (combat, combatant) => {
        console.log(combat, combatant, game);
        if (!isDM()) return;
    
        let token = canvas.tokens.objects.children.filter(token=>token.id===game.combat.nextCombatant.tokenId)[0];

        if (!token) return;

        //цикл обработки действий
        let baseSpeed = getSpeed(token.actor);
        //TODO собираем данные о персонаже и окружении

        //Расход ресурсов
        
        //выполняем действия
        let {action, conf} = getAction();//TODO
        //перемещение/упасть ничком
        if (action==='move') {
            move(token, conf)
        }

        //выбор цели
        if (action==='target'){
            target(token, conf)
        }

        //атака/заклинание/рывок/отход/уклонение/использование предмета/навыка
        //осмотреться / спрятаться
        if (action==='use'){
            use(token,conf)
        }

        //бонусное действие
        //реакция

    });

}
