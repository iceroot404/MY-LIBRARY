const adminEsc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function loadAdminFeatures() {
  try {
    const [usersR, moderationR, overviewR] = await Promise.all([fetch("/api/admin/users"), fetch("/api/admin/moderation"), fetch("/api/admin/overview")]);
    if (usersR.ok) {
      const data = await usersR.json();
      document.getElementById("admin-users-list").innerHTML = (data.users || []).map(u => `
        <div class="admin-user-row"><div><strong>${adminEsc(u.username)}</strong><div class="admin-feature-muted">${adminEsc(u.email)}</div></div>
        <button type="button" data-user-id="${u.id}" data-blocked="${u.blocked}">${u.blocked ? "Разблокировать" : "Заблокировать"}</button></div>`).join("") || "Нет читателей.";
    }
    if (moderationR.ok) {
      const d = await moderationR.json();
      const reports = (d.reports || []).map(r => `<div class="admin-mod-row"><div><strong>${adminEsc(r.book)}</strong><p>${adminEsc(r.content)}</p><small>Автор: ${adminEsc(r.author)} · Жалоба: ${adminEsc(r.reason)}</small></div><div><button data-resolve-report="${r.id}">Закрыть</button><button data-hide-post="${r.post_id}">Скрыть</button></div></div>`);
      const reviews = (d.reviews || []).map(r => `<div class="admin-mod-row"><div><strong>${adminEsc(r.book)} · ${adminEsc(r.username)}</strong><p>${adminEsc(r.text)}</p><small>${"★".repeat(r.rating)}</small></div><button data-delete-review="${r.id}">Удалить отзыв</button></div>`);
      const hidden = (d.hidden || []).map(r => `<div class="admin-mod-row"><div><strong>Скрыто: ${adminEsc(r.book)}</strong><p>${adminEsc(r.content)}</p></div><button data-restore-post="${r.id}">Восстановить</button></div>`);
      document.getElementById("admin-moderation-list").innerHTML = [...reports, ...reviews, ...hidden].join("") || "Нет материалов для модерации.";
    }
    if (overviewR.ok) {
      const d = await overviewR.json();
      document.getElementById("admin-top-books").innerHTML = (d.top_books || []).map((b, i) => `<div class="admin-top-row"><span>${i+1}. ${adminEsc(b.title)} — ${adminEsc(b.author)}</span><strong>${b.views} просмотров · ${b.downloads} скачиваний</strong></div>`).join("") || "Пока нет статистики.";
    }
  } catch (error) { console.error("Admin dashboard:", error); }
}
document.addEventListener("click", async e => {
  const user = e.target.closest("[data-user-id]");
  const resolve = e.target.closest("[data-resolve-report]");
  const hide = e.target.closest("[data-hide-post]");
  const restore = e.target.closest("[data-restore-post]");
  const review = e.target.closest("[data-delete-review]");
  let response;
  if (user) {
    response = await fetch(`/api/admin/users/${user.dataset.userId}/block`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({blocked:user.dataset.blocked !== "true"})});
  } else if (resolve) {
    response = await fetch(`/api/admin/reports/${resolve.dataset.resolveReport}/resolve`, {method:"POST"});
  } else if (hide || restore) {
    const id = (hide || restore).dataset[hide ? "hidePost" : "restorePost"];
    response = await fetch(`/api/admin/discussions/${id}/moderate`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({action: hide ? "hide" : "restore"})});
  } else if (review) {
    response = await fetch(`/api/admin/reviews/${review.dataset.deleteReview}/delete`, {method:"POST"});
  }
  if (response) { if (!response.ok) alert("Не удалось выполнить действие."); else loadAdminFeatures(); }
});
loadAdminFeatures();


(async function loadAdminTools(){
  const log = document.getElementById("admin-action-log");
  const trash = document.getElementById("admin-trash-list");
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  try {
    const [logResponse, trashResponse] = await Promise.all([fetch("/api/admin/actions"), fetch("/api/admin/trash")]);
    if (logResponse.ok && log) {
      const data = await logResponse.json();
      log.innerHTML = (data.items || []).map(item => `<div class="admin-mod-row"><div><strong>${esc(item.action)}</strong><p>${esc(item.details)}</p><small>${new Date(item.created_at).toLocaleString()}</small></div></div>`).join("") || "Действий пока нет.";
    }
    if (trashResponse.ok && trash) {
      const data = await trashResponse.json();
      trash.innerHTML = `<h3>Корзина книг (${(data.items || []).length})</h3>` + (data.items || []).map(book => `<div class="admin-mod-row"><div><strong>${esc(book.title)}</strong><p>${esc(book.author)}</p></div><button type="button" data-restore-book="${book.id}">Восстановить</button></div>`).join("");
    }
  } catch (error) { if (log) log.textContent = "Не удалось загрузить инструменты администратора."; }
})();
document.getElementById("admin-trash-list")?.addEventListener("click", async event => {
  const button = event.target.closest("[data-restore-book]"); if (!button) return;
  const response = await fetch(`/api/admin/books/${button.dataset.restoreBook}/restore`, {method:"POST"});
  if (response.ok) location.reload(); else alert("Не удалось восстановить книгу.");
});


(async function loadBookReports(){
  const host = document.getElementById("admin-book-reports");
  if (!host) return;
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  try {
    const response = await fetch("/api/admin/book-reports");
    if (!response.ok) throw new Error("Не удалось загрузить жалобы.");
    const data = await response.json();
    host.innerHTML = `<h3>Жалобы на книги (${(data.items || []).length})</h3>` + (data.items || []).map(item => `<div class="admin-mod-row"><div><strong>${esc(item.book)}</strong><p>${esc(item.reason)}</p><small>От: ${esc(item.author)} · ${new Date(item.created_at).toLocaleString()}</small></div><button type="button" data-resolve-book-report="${item.id}">Закрыть</button></div>`).join("") || "Жалоб на книги нет.";
  } catch (error) { host.textContent = error.message; }
})();
document.getElementById("admin-book-reports")?.addEventListener("click", async event => {
  const button = event.target.closest("[data-resolve-book-report]"); if (!button) return;
  const response = await fetch(`/api/admin/book-reports/${button.dataset.resolveBookReport}/resolve`, {method:"POST"});
  if (response.ok) location.reload(); else alert("Не удалось закрыть жалобу.");
});
