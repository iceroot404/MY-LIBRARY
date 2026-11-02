
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

setReaderTheme(document.documentElement.dataset.theme || localStorage.getItem("library-theme") || "light");

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
        window.applyEpubFontSize = (size) => rendition.themes.fontSize(`${size}px`);
        window.applyEpubFontFamily = (family) => rendition.themes.font("font-family", family);
        window.applyEpubFontSize(readerFontSize);
        const initialFont = reader.dataset.fontFamily || localStorage.getItem("reader-font-family") || "serif";
        const epubFonts = {serif: "Georgia, 'Times New Roman', serif", sans: "Arial, sans-serif", rounded: "'Trebuchet MS', Arial, sans-serif"};
        window.applyEpubFontFamily(epubFonts[initialFont] || epubFonts.serif);

        if (saved && saved.location) {
            await rendition.display(saved.location);
        } else {
            await rendition.display();
        window.displayEpubLocation = (cfi) => rendition.display(cfi);
        }

        rendition.on("relocated", (location) => {
            const cfi = location.start.cfi;
            window.currentEpubLocation = cfi;
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


// Улучшения читалки: масштаб, закладки и учёт времени чтения.
let readerFontSize = Number(reader.dataset.fontSize || localStorage.getItem("reader-font-size") || 18);
const readerFontSelect = document.getElementById("reader-font");
function applyReaderFontFamily(font) {
    const families = {serif: "Georgia, 'Times New Roman', serif", sans: "Arial, sans-serif", rounded: "'Trebuchet MS', Arial, sans-serif"};
    const selected = families[font] ? font : "serif";
    const family = families[selected];
    window.currentReaderFontFamily = selected;
    const text = document.getElementById("text-content");
    if (text) text.style.fontFamily = family;
    if (window.applyEpubFontFamily) window.applyEpubFontFamily(family);
    if (readerFontSelect) readerFontSelect.value = selected;
    try { localStorage.setItem("reader-font-family", selected); } catch {}
}
applyReaderFontFamily(reader.dataset.fontFamily || localStorage.getItem("reader-font-family") || "serif");
readerFontSelect?.addEventListener("change", e => applyReaderFontFamily(e.target.value));
readerFontSize = Math.max(14, Math.min(30, readerFontSize));
function applyReaderFontSize() {
    const text = document.getElementById("text-content");
    if (text) {
        text.style.fontSize = `${readerFontSize}px`;
        text.style.lineHeight = getComputedStyle(document.documentElement).getPropertyValue("--user-line-height") || "1.8";
    }
    if (window.applyEpubFontSize) window.applyEpubFontSize(readerFontSize);
    localStorage.setItem("reader-font-size", String(readerFontSize));
}
applyReaderFontSize();
document.getElementById("font-smaller")?.addEventListener("click", () => {
    readerFontSize = Math.max(14, readerFontSize - 1); applyReaderFontSize();
});
document.getElementById("font-larger")?.addEventListener("click", () => {
    readerFontSize = Math.min(30, readerFontSize + 1); applyReaderFontSize();
});

function getCurrentLocation() {
    if (format === "txt") {
        return String(document.querySelector(".text-reader-wrap")?.scrollTop || 0);
    }
    if (format === "epub" && window.currentEpubLocation) {
        return window.currentEpubLocation;
    }
    return "start";
}

async function loadBookmarks() {
    const list = document.getElementById("bookmark-list");
    if (!list || !loggedIn) return;
    try {
        const response = await fetch(`/api/bookmarks/${bookId}`);
        if (!response.ok) return;
        const data = await response.json();
        list.innerHTML = (data.items || []).map(item => `
            <div class="bookmark-row">
                <button type="button" data-jump-bookmark="${item.id}" data-location="${encodeURIComponent(item.location)}">${escapeText(item.label)}</button>
                <button type="button" data-delete-bookmark="${item.id}" aria-label="Удалить закладку">×</button>
            </div>
        `).join("") || "Закладок пока нет.";
    } catch { list.textContent = "Не удалось загрузить закладки."; }
}
function escapeText(value) {
    return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

document.getElementById("add-bookmark")?.addEventListener("click", async () => {
    if (!loggedIn) { location.href = "/login"; return; }
    const locationValue = getCurrentLocation();
    const label = prompt("Название закладки:", "Место чтения");
    if (label === null) return;
    const response = await fetch(`/api/bookmarks/${bookId}`, {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({location: locationValue, label})
    });
    if (response.ok) loadBookmarks();
    else alert("Не удалось сохранить закладку.");
});

document.getElementById("bookmark-list")?.addEventListener("click", async event => {
    const jump = event.target.closest("[data-jump-bookmark]");
    const del = event.target.closest("[data-delete-bookmark]");
    if (jump) {
        const locationValue = decodeURIComponent(jump.dataset.location);
        if (format === "txt") {
            const wrap = document.querySelector(".text-reader-wrap");
            if (wrap) wrap.scrollTop = Number(locationValue) || 0;
        } else if (format === "epub" && window.displayEpubLocation) {
            window.displayEpubLocation(locationValue);
        }
    }
    if (del) {
        await fetch(`/api/bookmarks/${del.dataset.deleteBookmark}`, {method:"DELETE"});
        loadBookmarks();
    }
});

loadBookmarks();
if (loggedIn) {
    let heartbeat = null;
    const startHeartbeat = () => {
        if (heartbeat) return;
        heartbeat = setInterval(() => {
            if (document.visibilityState === "visible") {
                fetch(`/api/reading-session/${bookId}`, {
                    method: "POST", headers: {"Content-Type":"application/json"},
                    body: JSON.stringify({seconds: 60})
                }).catch(() => {});
            }
        }, 60000);
    };
    startHeartbeat();
    window.addEventListener("beforeunload", () => clearInterval(heartbeat));
}
