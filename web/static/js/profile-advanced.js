(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(url, options = {}) {
    const response = await fetch(url, {headers:{'Content-Type':'application/json', ...(options.headers || {})}, ...options});
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw new Error(data.detail || 'Не удалось выполнить запрос.');
    return data;
  }

  async function loadGoal() {
    const host = $('reading-goal-summary');
    if (!host) return;
    try {
      const data = await api('/api/reading-goal');
      const percent = Math.min(100, Math.round((data.read_books / Math.max(1, data.target_books)) * 100));
      host.innerHTML = `<p>Прочитано <strong>${data.read_books}</strong> из <strong>${data.target_books}</strong> книг за ${data.year}</p><div class="goal-progress"><span style="width:${percent}%"></span></div><small>${percent}% цели · ${data.minutes_read} минут чтения</small>`;
      const form = $('reading-goal-form');
      if (form) { form.elements.target_books.value = data.target_books; form.elements.target_minutes.value = data.target_minutes; }
    } catch (error) { host.textContent = error.message; }
  }
  $('reading-goal-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const feedback = $('goal-feedback');
    try {
      await api('/api/reading-goal', {method:'POST', body:JSON.stringify({target_books:Number(form.elements.target_books.value), target_minutes:Number(form.elements.target_minutes.value)})});
      feedback.textContent = 'Цель сохранена.';
      loadGoal();
    } catch (error) { feedback.textContent = error.message; }
  });
  loadGoal();

  $('telegram-link-button')?.addEventListener('click', async () => {
    const output = $('telegram-link-info');
    output.textContent = 'Создаём код…';
    try {
      const data = await api('/api/telegram/link-code');
      output.textContent = `Открой своего Telegram-бота и отправь ему: ${data.command}. Код действует до следующего создания кода.`;
      if (navigator.clipboard?.writeText) navigator.clipboard.writeText(data.command).catch(() => {});
    } catch (error) { output.textContent = error.message; }
  });

  async function loadCollections() {
    const host = $('collection-list'); if (!host) return;
    try {
      const data = await api('/api/collections');
      host.innerHTML = (data.items || []).map(item => `<div class="advanced-item"><strong>${esc(item.title)}</strong> · ${item.count} книг ${item.is_shared ? `<small> · Общая ссылка: ${location.origin}/api/collections/shared/${encodeURIComponent(item.share_code)}</small>` : ''}</div>`).join('') || 'Пока нет коллекций.';
    } catch (error) { host.textContent = error.message; }
  }
  $('collection-form')?.addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget;
    try {
      await api('/api/collections', {method:'POST', body:JSON.stringify({title:form.elements.title.value, description:form.elements.description.value, is_shared:form.elements.is_shared.checked})});
      form.reset(); loadCollections();
    } catch (error) { alert(error.message); }
  });
  loadCollections();

  async function loadClubs() {
    const host = $('club-list'); if (!host) return;
    try {
      const data = await api('/api/clubs');
      host.innerHTML = (data.items || []).map(club => `<div class="advanced-item"><strong>${esc(club.title)}</strong><p>${esc(club.description)}</p><small>${club.members} участников</small> ${club.joined ? '<span>Вы состоите в клубе</span>' : `<button type="button" data-join-club="${club.id}">Вступить</button>`}</div>`).join('') || 'Пока нет книжных клубов.';
    } catch (error) { host.textContent = error.message; }
  }
  $('club-form')?.addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget;
    try { await api('/api/clubs', {method:'POST', body:JSON.stringify({title:form.elements.title.value, description:form.elements.description.value})}); form.reset(); loadClubs(); }
    catch (error) { alert(error.message); }
  });
  $('club-list')?.addEventListener('click', async event => {
    const button = event.target.closest('[data-join-club]'); if (!button) return;
    try { await api(`/api/clubs/${button.dataset.joinClub}/join`, {method:'POST'}); loadClubs(); }
    catch (error) { alert(error.message); }
  });
  loadClubs();
})();


(async function loadReadingCalendar(){
  const host = document.getElementById("reading-calendar"); if (!host) return;
  try {
    const response = await fetch("/api/reading-calendar");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Не удалось загрузить календарь.");
    const entries = Object.entries(data.days || {}).sort((a,b) => b[0].localeCompare(a[0])).slice(0,14);
    host.innerHTML = entries.length ? entries.map(([day, minutes]) => `<div class="advanced-item"><strong>${day}</strong> · ${minutes} мин.</div>`).join("") : "В этом году пока нет записей о чтении.";
  } catch (error) { host.textContent = error.message; }
})();
