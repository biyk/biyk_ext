export function addGMButton(onPlayClick){
    // Находим целевую кнопку создания боя
    const targetButton = document.querySelector("a.combat-button.combat-create");
    if (!targetButton) {
        console.warn("Кнопка создания боя не найдена. Попробуйте выполнить макрос позже.");
        return;
    }

    let saveBtn = document.getElementById("custom-text-save-btn");
    if (!saveBtn) {
        // Создаём новую кнопку
        saveBtn = document.createElement("a");
        saveBtn.id = "custom-text-save-btn";
        saveBtn.className = "combat-button";
        saveBtn.setAttribute("aria-label", "Сохранить текст");
        saveBtn.setAttribute("data-tooltip", "Сохранить текст в локальное хранилище");
        saveBtn.innerHTML = '<i class="fas fa-save"></i>';
        saveBtn.style.marginLeft = "4px"; // небольшой отступ

        // Добавляем обработчик клика (диалог с текстом)
        saveBtn.addEventListener("click", messageBox);
        targetButton.insertAdjacentElement("afterend", saveBtn);
    }

    // ▶ — ручной ход NPC deepVoyager, справа от custom-text-save-btn
    if (!document.getElementById("deepvoyager-play-btn")) {
        const playBtn = document.createElement("a");
        playBtn.id = "deepvoyager-play-btn";
        playBtn.className = "combat-button";
        playBtn.setAttribute("aria-label", "Ход ИИ");
        playBtn.setAttribute("data-tooltip", "Передать текущий ход NPC скрипту deepVoyager (/plan)");
        playBtn.innerHTML = '<i class="fas fa-play"></i>';
        playBtn.style.marginLeft = "4px";
        playBtn.addEventListener("click", () => onPlayClick && onPlayClick());
        saveBtn.insertAdjacentElement("afterend", playBtn);
    }
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