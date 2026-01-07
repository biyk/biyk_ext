// Скрипт для контроля экипировки предметов в руках
// Убедитесь, что запускается от имени ГМа
export function init() {

// Отслеживаем изменения в экипировке актора
    Hooks.on('preUpdateItem', async (item, system, options, userId) => {
       // console.log(item, system, options, userId)
        let actor = item.parent;
        let equipped = system.system?.equipped
        let hands = equipped?1:0;
        let needSlot = ['simpleM','simpleR','martialM','martialR', 'shield'].includes(item.system?.type.value)

        //если оно не требует слота или это не событие экипировки игнорируем
        if (!needSlot || !equipped) return console.log('Дополнительного слота не нужно',  needSlot , equipped);

        for (let item of actor.items){

            const needSlot = ['simpleM','simpleR','martialM','martialR', 'shield'].includes(item.system?.type?.value);
            const eq = item.system.equipped

            if (needSlot && eq){
                console.log(item.name);
                hands+= item.system?.properties.has('two')?2:1;
            }
        }
        console.log('требуется '+hands+' рук');

        if (hands > 2) {
            system.system.equipped = false;
            return false;
        }
    });

}
