
const $ = (id) => document.getElementById(id);

const grid = $("grid");
const filters = $("filters");
const count = $("count");
const empty = $("empty");
const modal = $("modal");
const modalBody = $("modal-body");

const state = {
    q: "",
    category: ""
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

let savedTheme = "light";

try {
    savedTheme =
        localStorage.getItem("library-theme") || "light";
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
        category: state.category
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
                    ${esc(book.author)}
                </p>

                <p class="desc">
                    ${
                        esc(book.description) ||
                        "Описание пока не добавлено."
                    }
                </p>

                ${actions}

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

            </div>

        </div>
    `;

    modal.showModal();

    loadReviews(book.id);

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
// ПЕРВАЯ ЗАГРУЗКА
// ===========================

load(true);