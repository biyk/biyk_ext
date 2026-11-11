import {log} from "../utils/logger.js";

/**
 * Снимает все цели пользователя (game.user.targets).
 *
 * dnd5e и midi-qol берут цель атаки из game.user.targets — это состояние общее на
 * пользователя и между ходами не чистится (AutoRemoveTargets = "dead" снимает только
 * мёртвых). Поэтому цель прошлого хода остаётся висеть и следующим бойцом
 * воспринимается как «его» цель: если прошлый ход били именно этого бойца, он
 * атакует сам себя. Чистим на старте каждого хода.
 */
export function clearTargets(reason = "") {
    if (!game.user?.targets?.size) return false;
    game.user.updateTokenTargets([]);
    if (reason) log.info(`сброшены висящие цели прошлых ходов (${reason})`);
    return true;
}

/**
 * Выбирает цель для действий хода.
 * @param {Token} token - токен, который действует
 * @param {Object} conf - { id: string } — id токена-цели
 * @returns {boolean} true, если цель реально выбрана
 */
export function target(token, conf) {
    const id = conf?.id;
    if (!id) {
        log.warn("ID цели не передан");
        return false;
    }

    // Себя целью не выбираем никогда: иначе следующее use() (атака) ударит по себе.
    if (token?.id === id) {
        log.warn(`попытка выбрать целью самого себя (${token.name}, ${id}) — пропуск`);
        return false;
    }

    const targetToken = canvas.tokens.placeables.find(t => t.id === id);
    if (!targetToken) {
        log.warn(`токен с ID ${id} не найден — цель не меняю`);
        return false;
    }

    // Не ставим союзников и себя в цели: иначе атака уйдёт по wrong target.
    const myDisp = token.document?.disposition ?? 0;
    if ((targetToken.document?.disposition ?? 0) === myDisp) {
        log.warn(`цель ${targetToken.name} (${id}) — союзник (disp=${myDisp}), пропускаю`);
        return false;
    }

    game.user.updateTokenTargets([id]);

    // updateTokenTargets не бросает ошибок: проверяем, что цель действительно встала.
    const applied = Array.from(game.user.targets).some(t => t.id === id);
    if (!applied) {
        log.warn(`цель ${targetToken.name} (${id}) не применилась`);
        return false;
    }

    log.info(`выбрана цель ${targetToken.name} (${id})`);
    return true;
}
