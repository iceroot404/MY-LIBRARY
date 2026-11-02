
const $ = (id) => document.getElementById(id);

const grid = $("grid");
const filters = $("filters");
const count = $("count");
const empty = $("empty");
const modal = $("modal");
const modalBody = $("modal-body");

const state = {
    q: "",
    category: "",
    sort: "newest"
};

const palette = [
    "#416d58",
    "#80566a",
    "#425b80",
    "#947b45",
    "#5e647e",
    "#52745f"
];

let books = [];
let timer = null;
let requestId = 0;


// ===========================
// ЗАЩИТА HTML
// ===========================

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => {
        const entities = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        };

        return entities[char];
    });
}


// ===========================
// СМЕНА ТЕМЫ
// ===========================

const themeButtons = document.querySelectorAll(
    "[data-theme-choice]"
);

const availableThemes = [
    "light",
    "dark",
    "sepia"
];

function setTheme(theme) {

    if (!availableThemes.includes(theme)) {
        theme = "light";
    }

    document.documentElement.dataset.theme = theme;

    try {
        localStorage.setItem("library-theme", theme);
    } catch (error) {
        console.warn("Не удалось сохранить тему.");
    }
    if (window.MY_LIBRARY_AUTHENTICATED) {
        fetch("/api/preferences/appearance", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({theme})
        }).catch(() => {});
    }

    themeButtons.forEach((button) => {

        const active =
            button.dataset.themeChoice === theme;

        button.classList.toggle("active", active);

        button.setAttribute(
            "aria-pressed",
            String(active)
        );
    });
}

let savedTheme = document.documentElement.dataset.theme || "light";

try {
    if (!window.MY_LIBRARY_AUTHENTICATED) {
        savedTheme = localStorage.getItem("library-theme") || savedTheme;
    }
} catch (error) {
    console.warn("Не удалось загрузить тему.");
}

setTheme(savedTheme);

themeButtons.forEach((button) => {

    button.addEventListener("click", () => {

        setTheme(button.dataset.themeChoice);

    });

});


// ===========================
// ОБЛОЖКА КНИГИ
// ===========================

function coverHTML(book) {

    if (book.cover) {

        return `
            <div class="cover">
                <img
                    src="${esc(book.cover)}"
                    alt="${esc(book.title)}"
                    loading="lazy"
                >
            </div>
        `;
    }

    const color =
        palette[Number(book.id) % palette.length];

    return `
        <div
            class="cover generated"
            style="background:${color}"
        >
            ${esc(book.title)}
        </div>
    `;
}


// ===========================
// КАРТОЧКА КНИГИ
// ===========================

function bookCard(book, index) {

    const delay = Math.min(index, 12) * 35;

    return `
        <article
            class="book-card"
            style="animation-delay:${delay}ms"
        >

            <button
                class="favorite-button ${book.is_favorite ? "active" : ""}"
                data-favorite-id="${book.id}"
                type="button"
                aria-label="Избранное"
                title="Добавить в избранное"
            >
                ${book.is_favorite ? "♥" : "♡"}
            </button>

            <button
                class="book-open"
                data-book-id="${book.id}"
                type="button"
            >

                ${coverHTML(book)}

                <h3>${esc(book.title)}</h3>

                <p>${esc(book.author)}</p>

            </button>
            <button class="compare-button" type="button" data-compare-id="${book.id}">Сравнить</button>

        </article>
    `;
}


// ===========================
// КАТЕГОРИИ
// ===========================

function renderFilters(categories) {

    const allCategories = [
        "",
        ...categories
    ];

    filters.innerHTML = allCategories
        .map((category) => {

            const active =
                category === state.category;

            return `
                <button
                    class="chip"
                    data-cat="${esc(category)}"
                    aria-pressed="${active}"
                    type="button"
                >
                    ${esc(category || "Все книги")}
                </button>
            `;

        })
        .join("");
}


// ===========================
// ПОКАЗ КНИГ
// ===========================

function renderBooks() {

    grid.innerHTML = books
        .map((book, index) => bookCard(book, index))
        .join("");

    empty.hidden = books.length > 0;

    count.textContent = `${books.length} ${
        books.length === 1 ? "книга" : "книг"
    }`;
}


// ===========================
// ЗАГРУЗКА КАТАЛОГА
// ===========================

async function load(updateFilters = false) {

    const current = ++requestId;

    const params = new URLSearchParams({
        q: state.q,
        category: state.category,
        sort: state.sort
    });

    try {

        const response = await fetch(
            `/api/books?${params}`
        );

        if (!response.ok) {
            throw new Error("Ошибка загрузки.");
        }

        const data = await response.json();

        if (current !== requestId) {
            return;
        }

        books = data.books || [];

        if (updateFilters) {
            renderFilters(data.categories || []);
        }

        renderBooks();

    } catch (error) {

        count.textContent =
            "Не удалось загрузить книги. Обновите страницу.";

        console.error(error);

    }
}


const sortSelect = $("sort-books");
if (sortSelect) {
    sortSelect.addEventListener("change", () => {
        state.sort = sortSelect.value;
        load();
    });
}

// ===========================
// ПОИСК
// ===========================

$("q").addEventListener("input", (event) => {

    clearTimeout(timer);

    timer = setTimeout(() => {

        state.q = event.target.value;

        load();

    }, 200);

});


// ===========================
// ФИЛЬТРЫ
// ===========================

filters.addEventListener("click", (event) => {

    const chip = event.target.closest(".chip");

    if (!chip) {
        return;
    }

    state.category = chip.dataset.cat;

    filters.querySelectorAll(".chip").forEach((item) => {

        item.setAttribute(
            "aria-pressed",
            String(item === chip)
        );

    });

    load();

});


// ===========================
// ИЗБРАННОЕ
// ===========================

async function toggleFavorite(bookId) {

    const book = books.find(
        (item) => Number(item.id) === bookId
    );

    if (!book) {
        return;
    }

    const method = book.is_favorite
        ? "DELETE"
        : "POST";

    try {

        const response = await fetch(
            `/api/favorites/${bookId}`,
            {
                method: method,
                credentials: "same-origin"
            }
        );

        if (response.status === 401) {
            location.href = "/login";
            return;
        }

        if (!response.ok) {
            throw new Error("Ошибка избранного.");
        }

        book.is_favorite = !book.is_favorite;

        renderBooks();

    } catch (error) {

        alert("Не удалось обновить избранное.");

        console.error(error);

    }
}


// Нажатие на сердечко
document.body.addEventListener("click", (event) => {

    const button = event.target.closest(
        "[data-favorite-id]"
    );

    if (!button) {
        return;
    }

    event.preventDefault();
    event.stopPropagation();

    toggleFavorite(
        Number(button.dataset.favoriteId)
    );

});


// ===========================
// ОТЗЫВЫ
// ===========================

async function loadReviews(bookId) {

    const container = $("review-list");

    if (!container) {
        return;
    }

    try {

        const response = await fetch(
            `/api/reviews/${bookId}`
        );

        if (!response.ok) {
            throw new Error();
        }

        const data = await response.json();

        container.innerHTML = (
            data.reviews || []
        ).map((review) => {

            return `
                <div class="review-item">

                    <strong>${esc(review.username)}</strong>

                    <span>
                        ${"★".repeat(review.rating)}
                    </span>

                    <p>${esc(review.text)}</p>

                </div>
            `;

        }).join("") || "<p>Пока нет отзывов.</p>";

    } catch {

        container.textContent =
            "Не удалось загрузить отзывы.";

    }
}



async function loadShelfStatus(bookId) {
    const select = $("book-shelf-status");
    if (!select) return;
    try {
        const response = await fetch("/api/shelves");
        if (response.status === 401) { select.value = ""; return; }
        if (!response.ok) return;
        const data = await response.json();
        const item = (data.items || []).find(x => Number(x.book.id) === Number(bookId));
        select.value = item ? item.status : "";
    } catch { select.value = ""; }
}

async function loadDiscussion(bookId) {
    const container = $("discussion-list");
    if (!container) return;
    try {
        const response = await fetch(`/api/discussions/${bookId}`);
        const data = await response.json();
        const items = data.items || [];
        container.innerHTML = items.map(item => `
            <article class="discussion-post ${item.parent_id ? "discussion-reply" : ""}">
                <div class="discussion-meta"><strong>${esc(item.username)}</strong><time>${new Date(item.created_at).toLocaleString()}</time></div>
                <p>${esc(item.content)}</p>
                <div class="discussion-actions">
                    <button type="button" data-discussion-like="${item.id}">♥ ${item.likes}</button>
                    ${item.can_report ? `<button type="button" data-discussion-report="${item.id}">Пожаловаться</button>` : ""}
                    ${!item.parent_id ? `<button type="button" data-discussion-reply="${item.id}">Ответить</button>` : ""}
                </div>
            </article>
        `).join("") || "<p>Пока нет обсуждений. Будьте первым!</p>";
    } catch { container.textContent = "Не удалось загрузить обсуждение."; }
}

document.body.addEventListener("click", async (event) => {
    const likeButton = event.target.closest("[data-discussion-like]");
    const reportButton = event.target.closest("[data-discussion-report]");
    const replyButton = event.target.closest("[data-discussion-reply]");
    const bookId = Number(modalBody.querySelector("[data-book-id]")?.dataset.bookId || 0);
    if (likeButton) {
        const response = await fetch(`/api/discussions/${likeButton.dataset.discussionLike}/like`, {method: "POST"});
        if (response.status === 401) { location.href = "/login"; return; }
        const data = await response.json();
        likeButton.textContent = `♥ ${data.likes}`;
        return;
    }
    if (reportButton) {
        const response = await fetch(`/api/discussions/${reportButton.dataset.discussionReport}/report`, {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({reason: "Жалоба читателя"})
        });
        if (response.status === 401) { location.href = "/login"; return; }
        alert(response.ok ? "Жалоба отправлена модератору." : "Не удалось отправить жалобу.");
        return;
    }
    if (replyButton) {
        const content = prompt("Ваш ответ:");
        if (!content) return;
        const post = replyButton.dataset.discussionReply;
        const book = books.find(x => Number(x.id) === Number(modal.dataset.bookId));
        if (!book) return;
        const response = await fetch(`/api/discussions/${book.id}`, {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({content, parent_id: Number(post)})
        });
        if (response.status === 401) { location.href = "/login"; return; }
        if (response.ok) loadDiscussion(book.id);
    }
});

// ===========================
// ОТКРЫТИЕ КНИГИ
// ===========================

async function openBook(book) {

    const extension = book.file
        ? (
            book.file
                .split("?")[0]
                .split(".")
                .pop() || ""
        ).toLowerCase()
        : "";

    const canRead = [
        "pdf",
        "epub",
        "txt"
    ].includes(extension);

    const actions = book.file
        ? `
            <div class="detail-actions">

                ${
                    canRead
                    ? `
                        <a
                            class="btn"
                            href="/read/${Number(book.id)}"
                        >
                            Читать онлайн ↗
                        </a>
                    `
                    : ""
                }

                <a
                    class="btn btn-secondary"
                    href="/download/${Number(book.id)}"
                >
                    Скачать книгу ↓
                </a>

            </div>
        `
        : `
            <p class="nofile">
                Файл книги пока не загружен.
            </p>
        `;

    modal.dataset.bookId = String(book.id);
    modalBody.innerHTML = `
        <div class="detail">

            ${coverHTML(book)}

            <div>

                <p
                    class="eyebrow"
                    style="color:var(--muted)"
                >
                    КНИГА / ${esc(book.category)}
                </p>

                <h2>${esc(book.title)}</h2>

                <p class="author">
                    <a href="/authors/${encodeURIComponent(book.author)}">${esc(book.author)}</a>
                </p>

                <p class="desc">
                    ${
                        esc(book.description) ||
                        "Описание пока не добавлено."
                    }
                </p>

                ${actions}

                <div class="library-tools">
                    <label for="book-shelf-status">Моя книжная полка</label>
                    <select id="book-shelf-status">
                        <option value="">Не добавлена</option>
                        <option value="want">Хочу прочитать</option>
                        <option value="reading">Читаю</option>
                        <option value="read">Прочитано</option>
                    </select>
                    <span id="shelf-feedback" role="status"></span>
                    <button type="button" id="report-book">Сообщить об ошибке</button>
                </div>

                <div class="review-area">

                    <h3>Отзывы и оценки</h3>

                    <div id="review-list">
                        Загружаем отзывы...
                    </div>

                    <form id="review-form">

                        <select name="rating" required>
                            <option value="5">★★★★★ — Отлично</option>
                            <option value="4">★★★★ — Хорошо</option>
                            <option value="3">★★★ — Нормально</option>
                            <option value="2">★★ — Не очень</option>
                            <option value="1">★ — Плохо</option>
                        </select>

                        <textarea
                            name="text"
                            maxlength="3000"
                            placeholder="Ваш отзыв..."
                        ></textarea>

                        <button
                            class="btn"
                            type="submit"
                        >
                            Отправить отзыв
                        </button>

                    </form>

                </div>

                <div class="discussion-area">
                    <h3>Обсуждение книги</h3>
                    <div id="discussion-list" class="discussion-list">Загружаем обсуждение...</div>
                    <form id="discussion-form">
                        <textarea name="content" maxlength="3000" placeholder="Поделитесь мыслями о книге..." required></textarea>
                        <button class="btn" type="submit">Опубликовать</button>
                    </form>
                </div>

            </div>

        </div>
    `;

    modal.showModal();

    loadReviews(book.id);
    loadShelfStatus(book.id);
    loadDiscussion(book.id);

    const shelfSelect = $("book-shelf-status");
    shelfSelect?.addEventListener("change", async () => {
        if (!shelfSelect.value) {
            await fetch(`/api/shelves/${book.id}`, {method: "DELETE"});
            $("shelf-feedback").textContent = "Убрано с полки";
            return;
        }
        const response = await fetch(`/api/shelves/${book.id}`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({status: shelfSelect.value})
        });
        if (response.status === 401) { location.href = "/login"; return; }
        $("shelf-feedback").textContent = response.ok ? "Сохранено" : "Ошибка сохранения";
    });

    $("report-book")?.addEventListener("click", async () => {
        const reason = prompt("Опишите ошибку в книге: неверная обложка, автор, файл и т. д.");
        if (!reason) return;
        try {
            const response = await fetch(`/api/books/${book.id}/report`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({reason})});
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || "Не удалось отправить жалобу.");
            alert("Спасибо! Сообщение отправлено администратору.");
        } catch (error) { alert(error.message); }
    });

    const discussionForm = $("discussion-form");
    discussionForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const content = new FormData(discussionForm).get("content");
        const response = await fetch(`/api/discussions/${book.id}`, {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({content})
        });
        if (response.status === 401) { location.href = "/login"; return; }
        if (!response.ok) { alert("Не удалось опубликовать сообщение."); return; }
        discussionForm.reset();
        loadDiscussion(book.id);
    });

    $("review-form").addEventListener(
        "submit",
        async (event) => {

            event.preventDefault();

            const reviewForm = event.currentTarget;

            const form = new FormData(reviewForm);

            try {

                const response = await fetch(
                    `/api/reviews/${book.id}`,
                    {
                        method: "POST",
                        credentials: "same-origin",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({
                            rating: Number(form.get("rating")),
                            text: form.get("text")
                        })
                    }
                );

                if (response.status === 401) {
                    location.href = "/login";
                    return;
                }

                if (!response.ok) {
                    throw new Error();
                }

                reviewForm.reset();

                loadReviews(book.id);

            } catch {

                alert("Не удалось отправить отзыв.");

            }

        }
    );

}


// ===========================
// ОТКРЫТИЕ КАРТОЧКИ
// ===========================

document.body.addEventListener("click", (event) => {

    const button = event.target.closest(".book-open");

    if (!button) {
        return;
    }

    const bookId = Number(button.dataset.bookId);

    const book = books.find(
        (item) => Number(item.id) === bookId
    );

    if (book) {
        openBook(book);
    }

});


// ===========================
// ЗАКРЫТИЕ ОКНА
// ===========================

$("close").addEventListener("click", () => {
    modal.close();
});

modal.addEventListener("click", (event) => {

    if (event.target === modal) {
        modal.close();
    }

});


// ===========================
// СРАВНЕНИЕ КНИГ
// ===========================
const compareSelection = new Set();
function updateCompareBar() {
    const bar = $("compare-bar");
    const countNode = $("compare-count");
    if (!bar || !countNode) return;
    bar.hidden = compareSelection.size === 0;
    countNode.textContent = `Выбрано ${compareSelection.size} книг`;
    document.querySelectorAll("[data-compare-id]").forEach(button => {
        const active = compareSelection.has(Number(button.dataset.compareId));
        button.classList.toggle("selected", active);
        button.textContent = active ? "Выбрано ✓" : "Сравнить";
    });
}
grid?.addEventListener("click", event => {
    const button = event.target.closest("[data-compare-id]");
    if (!button) return;
    const id = Number(button.dataset.compareId);
    if (compareSelection.has(id)) compareSelection.delete(id);
    else if (compareSelection.size < 4) compareSelection.add(id);
    else return alert("Можно сравнить не более 4 книг.");
    updateCompareBar();
});
$("compare-clear")?.addEventListener("click", () => { compareSelection.clear(); updateCompareBar(); });
$("compare-open")?.addEventListener("click", async () => {
    if (compareSelection.size < 2) return alert("Выберите минимум две книги.");
    try {
        const response = await fetch(`/api/books/compare?ids=${Array.from(compareSelection).join(",")}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Ошибка сравнения.");
        $("compare-content").innerHTML = `<div class="compare-grid">${(data.items || []).map(book => `<article><strong>${esc(book.title)}</strong><p>${esc(book.author)}</p><p>Категория: ${esc(book.category)}</p><p>Просмотры: ${book.view_count}</p><p>Скачивания: ${book.download_count}</p></article>`).join("")}</div>`;
        $("compare-modal").showModal();
    } catch (error) { alert(error.message); }
});
$("compare-close")?.addEventListener("click", () => $("compare-modal").close());

// ===========================
// ПЕРВАЯ ЗАГРУЗКА
// ===========================

load(true);


// ===========================
// ОБРАБОТКА ЗАКАЗА КНИГИ
// ===========================

const bookRequestForm = $("book-request-form");

if (bookRequestForm) {
    bookRequestForm.addEventListener("submit", async (event) => {
        event.preventDefault();

        const button = bookRequestForm.querySelector(
            'button[type="submit"]'
        );
        const result = $("book-request-result");

        button.disabled = true;
        result.textContent = "Отправляем заявку...";

        try {
            const body = new URLSearchParams(
                new FormData(bookRequestForm)
            );

            const response = await fetch("/api/book-requests", {
                method: "POST",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                body: body
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || "Ошибка отправки");
            }

            bookRequestForm.reset();

            if (data.notified) {
                result.textContent =
                    `Заявка №${data.id} отправлена! Спасибо.`;
            } else {
                result.textContent =
                    "Заявка сохранена, но Telegram не отправил уведомление. "
                    + "Попробуйте связаться с администрацией.";
            }

        } catch (error) {
            result.textContent =
                error.message || "Не удалось отправить заявку.";
        } finally {
            button.disabled = false;
        }
    });
}
