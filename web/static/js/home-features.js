(() => {
  const byId = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const linkFor = book => book.file ? `/read/${Number(book.id)}` : `/authors/${encodeURIComponent(book.author || '')}`;
  const imageFor = book => book.cover
    ? `<img src="${esc(book.cover)}" alt="Обложка ${esc(book.title)}" loading="lazy">`
    : `<div class="home-feature-placeholder">${esc(book.title)}</div>`;

  async function loadBookOfDay() {
    const host = byId('book-of-day');
    if (!host) return;
    try {
      const response = await fetch('/api/book-of-day');
      const data = await response.json();
      if (!response.ok || !data.book) throw new Error('Пока нет доступных книг.');
      const book = data.book;
      host.innerHTML = `<a class="featured-book" href="${linkFor(book)}">${imageFor(book)}<span><strong>${esc(book.title)}</strong><small>${esc(book.author)}</small></span></a>`;
    } catch (error) { host.textContent = error.message || 'Не удалось загрузить книгу дня.'; }
  }

  async function loadRecommendations() {
    const host = byId('recommendations');
    if (!host) return;
    try {
      const response = await fetch('/api/recommendations?limit=6');
      const data = await response.json();
      if (!response.ok) throw new Error('Не удалось загрузить подборку.');
      const items = data.items || [];
      host.innerHTML = items.length ? items.map(book => `<a class="recommendation-item" href="${linkFor(book)}">${imageFor(book)}<span><strong>${esc(book.title)}</strong><small>${esc(book.author)}</small></span></a>`).join('') : 'Добавьте книги в библиотеку, чтобы получить подборку.';
    } catch (error) { host.textContent = error.message; }
  }
  loadBookOfDay();
  loadRecommendations();
})();
