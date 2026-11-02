(() => {
  const root = document.getElementById('reader');
  const form = document.getElementById('reader-note-form');
  const list = document.getElementById('reader-note-list');
  if (!root || !form || !list) return;
  const bookId = Number(root.dataset.bookId);
  const loggedIn = root.dataset.loggedIn === 'true';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  if (!loggedIn) { list.textContent = 'Войдите в аккаунт, чтобы сохранять заметки.'; form.hidden = true; return; }

  async function load() {
    try {
      const response = await fetch(`/api/notes/${bookId}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Ошибка загрузки заметок.');
      list.innerHTML = (data.items || []).map(item => `<article class="bookmark-row"><div>${item.quote ? `<blockquote>${esc(item.quote)}</blockquote>` : ''}<p>${esc(item.content)}</p><small>${new Date(item.created_at).toLocaleString()}</small></div><button type="button" data-delete-note="${item.id}" aria-label="Удалить заметку">×</button></article>`).join('') || 'Заметок пока нет.';
    } catch (error) { list.textContent = error.message; }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const body = {content:form.elements.content.value, quote:form.elements.quote.value, location:window.currentEpubLocation || String(document.querySelector('.text-reader-wrap')?.scrollTop || 0)};
    try {
      const response = await fetch(`/api/notes/${bookId}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Не удалось сохранить заметку.');
      form.reset(); load();
    } catch (error) { alert(error.message); }
  });
  list.addEventListener('click', async event => {
    const button = event.target.closest('[data-delete-note]'); if (!button) return;
    await fetch(`/api/notes/${button.dataset.deleteNote}`, {method:'DELETE'}); load();
  });
  load();
})();
