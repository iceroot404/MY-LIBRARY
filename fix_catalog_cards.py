from pathlib import Path
import sys

CSS_PATH = Path('web/static/css/style.css')
MARKER = '/* MY_LIBRARY_CATALOG_CARDS_FIX_V1 */'
PATCH = r'''

/* MY_LIBRARY_CATALOG_CARDS_FIX_V1 */
/* Единый аккуратный вид карточек каталога */
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(170px, 205px));
    justify-content: start;
    align-items: start;
    gap: 30px 24px;
    padding-bottom: 90px;
}

.book-card {
    position: relative;
    display: flex;
    flex-direction: column;
    width: 100%;
    min-width: 0;
    animation: appear .35s both;
}

.book-open {
    all: unset;
    display: block;
    width: 100%;
    min-width: 0;
    box-sizing: border-box;
    color: var(--ink);
    cursor: pointer;
    text-align: left;
}

.book-card .cover {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: auto;
    aspect-ratio: 2 / 3;
    overflow: hidden;
    position: relative;
    box-sizing: border-box;
    border-radius: 7px 11px 11px 7px;
    background: var(--surface, #f0eee7);
    box-shadow: inset 5px 0 0 #00000012, 0 8px 22px #00000018;
    transition: transform .22s ease, box-shadow .22s ease;
}

.book-card .cover img {
    display: block;
    width: 100%;
    height: 100%;
    max-width: 100%;
    object-fit: contain;
    object-position: center;
}

.book-card .cover.generated {
    align-items: flex-end;
    justify-content: flex-start;
    padding: 18px;
    color: #fff;
    font: 700 19px/1.25 'Playfair Display', Georgia, serif;
    overflow-wrap: anywhere;
}

.book-card:hover .cover {
    transform: translateY(-5px);
    box-shadow: inset 5px 0 0 #00000012, 0 15px 28px #00000024;
}

.book-open h3 {
    display: -webkit-box;
    min-height: 2.7em;
    margin: 12px 2px 4px;
    overflow: hidden;
    color: var(--ink);
    font: 600 13px/1.35 'DM Sans', sans-serif;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
}

.book-open p {
    display: -webkit-box;
    margin: 0 2px;
    overflow: hidden;
    color: var(--muted);
    font: 400 11px/1.45 'DM Sans', sans-serif;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
}

.favorite-button {
    position: absolute;
    z-index: 2;
    top: 9px;
    right: 9px;
    display: grid;
    place-items: center;
    width: 34px;
    height: 34px;
    padding: 0;
    border: 1px solid #ffffff80;
    border-radius: 50%;
    background: #17231dcc;
    color: #fff;
    font-size: 18px;
    line-height: 1;
    cursor: pointer;
    box-shadow: 0 3px 10px #0002;
    backdrop-filter: blur(6px);
    transition: transform .2s, background .2s;
}

.favorite-button:hover {
    transform: scale(1.08);
}

.favorite-button.active {
    background: #a94354;
    color: #fff;
}

.book-open:focus-visible .cover,
.favorite-button:focus-visible {
    outline: 3px solid #d7b56d;
    outline-offset: 3px;
}

@media (max-width: 600px) {
    .grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 24px 15px;
    }

    .book-open h3 {
        font-size: 12px;
    }
}
'''

def main() -> int:
    if not CSS_PATH.is_file():
        print('ОШИБКА: не найден web/static/css/style.css.')
        print('Запусти скрипт из корневой папки проекта MY-LIBRARY.')
        return 1

    css = CSS_PATH.read_text(encoding='utf-8')
    if MARKER in css:
        print('Исправление карточек уже установлено. Повторное добавление не требуется.')
        return 0

    CSS_PATH.write_text(css.rstrip() + PATCH + '\n', encoding='utf-8')
    print('Готово: стили карточек каталога обновлены.')
    print('Обнови страницу сайта сочетанием Ctrl + Shift + R.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
