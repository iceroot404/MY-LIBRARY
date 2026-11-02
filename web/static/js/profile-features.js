const shelfContainer = document.getElementById("shelf-items");
const summaryContainer = document.getElementById("reading-summary");
let shelfItems = [];
let activeShelf = "want";
const escProfile = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function renderShelf() {
  if (!shelfContainer) return;
  const items = shelfItems.filter(x => x.status === activeShelf);
  shelfContainer.innerHTML = items.map(x => `
    <article class="profile-book">
      <a class="profile-book-cover" href="/read/${x.book.id}">${x.book.cover ? `<img src="${escProfile(x.book.cover)}" alt="">` : `<span>${escProfile(x.book.title)}</span>`}</a>
      <strong>${escProfile(x.book.title)}</strong><small>${escProfile(x.book.author)}</small>
      ${x.book.file ? `<a class="profile-read" href="/read/${x.book.id}">Читать →</a>` : ""}
      <button type="button" data-remove-shelf="${x.book.id}">Убрать с полки</button>
    </article>`).join("") || `<p class="empty-profile">На этой полке пока нет книг.</p>`;
  document.querySelectorAll("[data-shelf-tab]").forEach(b => b.classList.toggle("active", b.dataset.shelfTab === activeShelf));
}
async function loadProfileFeatures() {
  try {
    const [shelvesResponse, summaryResponse] = await Promise.all([fetch("/api/shelves"), fetch("/api/reading-summary")]);
    if (shelvesResponse.ok) { shelfItems = (await shelvesResponse.json()).items || []; renderShelf(); }
    if (summaryResponse.ok) {
      const d = await summaryResponse.json();
      summaryContainer.innerHTML = `
        <article class="summary-mini"><span>📖</span><strong>${d.started_books}</strong><small>Начато книг</small></article>
        <article class="summary-mini"><span>✅</span><strong>${d.finished_books}</strong><small>Прочитано</small></article>
        <article class="summary-mini"><span>⏱</span><strong>${d.minutes_read} мин</strong><small>Время чтения</small></article>`;
    }
  } catch { if (shelfContainer) shelfContainer.textContent = "Не удалось загрузить полки."; }
}
document.querySelectorAll("[data-shelf-tab]").forEach(b => b.addEventListener("click", () => { activeShelf = b.dataset.shelfTab; renderShelf(); }));
shelfContainer?.addEventListener("click", async e => {
  const b = e.target.closest("[data-remove-shelf]"); if (!b) return;
  await fetch(`/api/shelves/${b.dataset.removeShelf}`, {method:"DELETE"});
  shelfItems = shelfItems.filter(x => Number(x.book.id) !== Number(b.dataset.removeShelf)); renderShelf();
});
loadProfileFeatures();
