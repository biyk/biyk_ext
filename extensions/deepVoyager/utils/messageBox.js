export function addGMButton(){
    if (document.getElementById("custom-text-save-btn")) return;

    // Находим целевую кнопку создания боя
    const targetButton = document.querySelector("a.combat-button.combat-create");
    if (!targetButton) {
        console.warn("Кнопка создания боя не найдена. Попробуйте выполнить макрос позже.");
        return;
    }

    // Создаём новую кнопку
    const newButton = document.createElement("a");
    newButton.id = "custom-text-save-btn";
    newButton.className = "combat-button";
    newButton.setAttribute("aria-label", "Сохранить текст");
    newButton.setAttribute("data-tooltip", "Сохранить текст в локальное хранилище");
    newButton.innerHTML = '<i class="fas fa-save"></i>';
    newButton.style.marginLeft = "4px"; // небольшой отступ

    // Добавляем обработчик клика (диалог с текстом)
    newButton.addEventListener("click", messageBox);
    targetButton.insertAdjacentElement("afterend", newButton);

}
function messageBox(){
    // Макрос для сохранения и загрузки текста из localStorage
    const STORAGE_KEY = "gmNotes";

// Получаем ранее сохранённый текст (если есть)
    const savedText = localStorage.getItem(STORAGE_KEY) || "";

// Создаём диалоговое окно
    new Dialog({
        title: "Ввод текста",
        content: `
        <div style="margin-bottom: 1em;">
            <label for="macro-text">Введите текст:</label>
            <textarea id="macro-text" rows="5" style="width: 100%; resize: vertical;">${savedText.replace(/</g, "&lt;")}</textarea>
        </div>
    `,
        buttons: {
            ok: {
                icon: '<i class="fas fa-check"></i>',
                label: "OK",
                callback: (html) => {
                    const newText = html.find("#macro-text").val();
                    localStorage.setItem(STORAGE_KEY, newText);
                    ui.notifications.info("Текст сохранён в localStorage");
                    // При необходимости можно выполнить дополнительные действия с текстом
                    console.log("Сохранённый текст:", newText);
                }
            },
            cancel: {
                icon: '<i class="fas fa-times"></i>',
                label: "Отмена",
                callback: () => console.log("Диалог закрыт без сохранения")
            }
        },
        default: "ok"
    }).render(true);
}