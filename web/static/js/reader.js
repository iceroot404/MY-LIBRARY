
const reader = document.getElementById("reader");

const bookId = Number(reader.dataset.bookId);
const format = reader.dataset.format;
const fileUrl = reader.dataset.fileUrl;
const loggedIn = reader.dataset.loggedIn === "true";

const themeSelect = document.getElementById("reader-theme");

function setReaderTheme(theme) {
    if (!["light", "dark", "sepia"].includes(theme)) {
        theme = "light";
    }

    document.documentElement.dataset.theme = theme;

    localStorage.setItem("library-theme", theme);

    if (themeSelect) {
        themeSelect.value = theme;
    }
}

setReaderTheme(localStorage.getItem("library-theme") || "light");

themeSelect?.addEventListener("change", (event) => {
    setReaderTheme(event.target.value);
});

async function getSavedProgress() {
    if (!loggedIn) {
        return null;
    }

    try {
        const response = await fetch(`/api/reading-progress/${bookId}`);

        if (!response.ok) {
            return null;
        }

        return await response.json();
    } catch {
        return null;
    }
}

let saveTimer = null;

async function saveProgress(location, percent) {
    if (!loggedIn) {
        return;
    }

    clearTimeout(saveTimer);

    saveTimer = setTimeout(async () => {
        try {
            await fetch(`/api/reading-progress/${bookId}`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    location: String(location),
                    percent: Number(percent)
                })
            });
        } catch {
            console.error("Не удалось сохранить прогресс чтения.");
        }
    }, 700);
}

// TXT

async function initTextReader() {
    const content = document.getElementById("text-content");
    const container = document.querySelector(".text-reader-wrap");

    try {
        const response = await fetch(fileUrl);

        if (!response.ok) {
            throw new Error("Не удалось открыть текст книги.");
        }

        content.textContent = await response.text();

        const saved = await getSavedProgress();

        if (saved && saved.location) {
            container.scrollTop = Number(saved.location) || 0;
        }

        container.addEventListener("scroll", () => {
            const maxScroll =
                container.scrollHeight - container.clientHeight;

            const percent = maxScroll > 0
                ? (container.scrollTop / maxScroll) * 100
                : 0;

            saveProgress(
                String(container.scrollTop),
                percent
            );
        });

    } catch (error) {
        content.textContent = "Ошибка загрузки книги. Проверьте файл.";
    }
}

// EPUB

async function initEpubReader() {
    const status = document.getElementById("epub-status");

    if (typeof ePub === "undefined") {
        status.textContent = "Не удалось загрузить EPUB-просмотрщик.";
        return;
    }

    try {
        const saved = await getSavedProgress();

        const book = ePub(fileUrl);

        const rendition = book.renderTo("epub-viewer", {
            width: "100%",
            height: "100%",
            flow: "paginated",
            spread: "auto"
        });

        await book.ready;

        if (saved && saved.location) {
            await rendition.display(saved.location);
        } else {
            await rendition.display();
        }

        rendition.on("relocated", (location) => {
            const cfi = location.start.cfi;
            const percentage = location.start.percentage || 0;

            status.textContent =
                `${Math.round(percentage * 100)}% прочитано`;

            saveProgress(
                cfi,
                percentage * 100
            );
        });

        document.getElementById("prev-page").addEventListener(
            "click",
            () => rendition.prev()
        );

        document.getElementById("next-page").addEventListener(
            "click",
            () => rendition.next()
        );

        window.addEventListener("beforeunload", () => {
            book.destroy();
        });

    } catch (error) {
        status.textContent = "Не удалось открыть EPUB-книгу.";
        console.error(error);
    }
}

// ЗАПУСК

if (format === "txt") {
    initTextReader();
}

if (format === "epub") {
    initEpubReader();
}
