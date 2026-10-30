/* Menu page: shows the menu from the API. Everyone sees Add / Edit / Delete / Mark unavailable;
   if the owner is not signed in, clicking one opens the login and then carries on with that action.
   The server still enforces the owner session on every change. */
(() => {
  'use strict';
  const root = document.getElementById('menu-root');
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const rid = root.dataset.restaurantId;
  let currency = 'PKR', items = [], owner = false, busy = false, pending = null, loginOpen = false;

  async function api(path, opts = {}) {
    const res = await fetch(path, { credentials: 'same-origin', ...opts,
      headers: { ...(opts.body ? { 'Content-Type': 'application/json' } : {}) } });
    if (!res.ok) {
      let detail = 'Request failed (' + res.status + ')';
      try { const j = await res.json(); detail = typeof j.detail === 'string' ? j.detail : j.detail.map((d) => d.msg).join('; '); } catch (_) { /* ignore */ }
      const e = new Error(detail); e.status = res.status; throw e;
    }
    return res.json();
  }
  const el = (tag, cls, t) => { const n = document.createElement(tag); if (cls) n.className = cls; if (t !== undefined) n.textContent = t; return n; };
  const button = (label, cls, onClick) => { const b = el('button', cls, label); b.type = 'button'; b.onclick = onClick; return b; };
  const notice = (msg) => { $('menu-status').textContent = msg; };

  /* ---------- rendering ---------- */
  function render() {
    const list = $('menu-list'); list.replaceChildren();
    const cats = [...new Set(items.map((i) => i.category))];
    $('cat-list').replaceChildren(...cats.map((c) => { const o = document.createElement('option'); o.value = c; return o; }));
    if (!items.length) { notice('The menu is empty. Click "+ Add new item" to add your first dish.'); return; }
    notice(items.length + (items.length === 1 ? ' dish' : ' dishes') + ' in ' + cats.length + (cats.length === 1 ? ' category' : ' categories') + '.');
    cats.forEach((cat) => {
      list.appendChild(el('h2', '', cat));
      items.filter((i) => i.category === cat).forEach((i) => {
        const card = el('article', 'card' + (i.available ? '' : ' off'));
        const left = el('div', 'card-main');
        left.appendChild(el('h3', '', i.name));
        if (i.description) left.appendChild(el('p', 'muted', i.description));
        if (i.options.length) left.appendChild(el('p', 'muted', 'Options: ' + i.options.join(', ')));
        left.appendChild(el('span', 'badge' + (i.available ? '' : ' off'), i.available ? 'Available' : 'Unavailable'));
        const right = el('div', 'card-side');
        right.appendChild(el('div', 'price', i.price));
        const actions = el('div', 'actions');
        actions.append(
          button('Edit', 'btn small', () => asOwner(() => openForm(i))),
          button(i.available ? 'Mark unavailable' : 'Mark available', 'btn small', () => asOwner(() => toggle(i))),
          button('Delete', 'btn small danger', () => asOwner(() => remove(i))));
        right.appendChild(actions);
        card.append(left, right); list.appendChild(card);
      });
    });
  }

  async function load() {
    try {
      const d = await api('/api/menu?restaurant_id=' + encodeURIComponent(rid));
      currency = d.restaurant.currency; items = d.items; $('f-currency').textContent = currency; render();
    } catch (e) { notice('Could not load the menu: ' + e.message); }
  }

  /* ---------- owner session ---------- */
  function syncOwnerUi() {
    $('btn-signin').hidden = owner; $('logout').hidden = !owner;
    $('login-form').hidden = owner || !loginOpen;
    $('owner-panel').hidden = !owner;
    $('owner-section').hidden = !(owner || loginOpen);
  }
  function setOwner(on) { owner = on; if (on) loginOpen = false; else closeForm(); syncOwnerUi(); }
  function showLogin(msg) {
    loginOpen = true; $('login-error').hidden = true;
    $('login-msg').textContent = msg || 'Sign in to add, edit or delete dishes.';
    syncOwnerUi(); $('owner-section').scrollIntoView({ block: 'center' }); $('login-password').focus();
  }
  /* Run an owner-only action now, or ask for the login first and run it right after signing in. */
  function asOwner(action) {
    if (owner) { action(); return; }
    pending = action; showLogin('Sign in as owner to continue.');
  }
  function sessionExpired(retry) {
    setOwner(false); pending = retry || null; showLogin('Your session expired. Please sign in again.');
  }

  /* ---------- item form ---------- */
  function closeForm() { $('item-form').reset(); $('f-id').value = ''; $('item-error').hidden = true; $('item-form').hidden = true; }
  function openForm(item) {
    $('item-form').reset(); $('item-error').hidden = true;
    if (item) {
      $('item-form-title').textContent = 'Edit item: ' + item.name; $('f-id').value = item.id; $('f-name').value = item.name;
      $('f-desc').value = item.description; $('f-cat').value = item.category; $('f-price').value = (item.price_minor / 100).toFixed(2);
      $('f-opts').value = item.options.join(', '); $('f-avail').checked = item.available;
    } else { $('item-form-title').textContent = 'Add new item'; $('f-id').value = ''; $('f-avail').checked = true; }
    $('item-form').hidden = false; $('item-form').scrollIntoView({ block: 'center' }); $('f-name').focus();
  }

  async function toggle(i) {
    if (busy) return; busy = true;
    try { await api('/api/menu/items/' + encodeURIComponent(i.id) + '/availability', { method: 'PATCH', body: JSON.stringify({ available: !i.available }) });
      await load(); notice(i.name + ' is now ' + (i.available ? 'unavailable' : 'available') + '.'); }
    catch (e) { if (e.status === 401) sessionExpired(() => toggle(i)); else notice(e.message); }
    finally { busy = false; }
  }
  async function remove(i) {
    if (busy) return;
    if (!window.confirm('Delete "' + i.name + '"? This cannot be undone.')) return;   // destructive: always confirm
    busy = true;
    try {
      await api('/api/menu/items/' + encodeURIComponent(i.id), { method: 'DELETE' });
      if ($('f-id').value === i.id) closeForm();                   // don't leave a deleted item in the edit form
      await load(); notice('Deleted "' + i.name + '".');
    } catch (e) {
      if (e.status === 401) sessionExpired(() => remove(i));
      else { await load(); notice(e.status === 404 ? 'That item no longer exists. The menu was refreshed.' : e.message); }
    } finally { busy = false; }
  }

  /* ---------- events ---------- */
  $('btn-add').addEventListener('click', () => asOwner(() => openForm(null)));
  $('btn-signin').addEventListener('click', () => { pending = null; showLogin(); });
  $('login-cancel').addEventListener('click', () => { pending = null; loginOpen = false; syncOwnerUi(); });
  $('login-form').addEventListener('submit', async (ev) => {
    ev.preventDefault(); const err = $('login-error'); err.hidden = true;
    try {
      await api('/api/owner/login', { method: 'POST', body: JSON.stringify({ restaurant_id: rid, password: $('login-password').value }) });
      $('login-password').value = ''; setOwner(true);
      const next = pending; pending = null;
      if (next) next(); else notice('Signed in. You can now add, edit and delete dishes.');
    } catch (e) { err.textContent = e.message; err.hidden = false; }
  });
  $('logout').addEventListener('click', async () => { await api('/api/owner/logout', { method: 'POST' }).catch(() => {}); setOwner(false); notice('Signed out.'); await load(); });
  $('f-reset').addEventListener('click', closeForm);
  $('item-form').addEventListener('submit', async (ev) => {
    ev.preventDefault(); const err = $('item-error'); err.hidden = true;
    if (busy) return;                                              // duplicate-submission guard
    const id = $('f-id').value;
    const body = JSON.stringify({ name: $('f-name').value, description: $('f-desc').value, category: $('f-cat').value,
      price_minor: Math.round(parseFloat($('f-price').value) * 100), available: $('f-avail').checked,
      options: $('f-opts').value.split(',').map((s) => s.trim()).filter(Boolean) });
    const btn = $('item-form').querySelector('button[type=submit]');
    busy = true; btn.disabled = true;
    try { await api(id ? '/api/menu/items/' + encodeURIComponent(id) : '/api/menu/items', { method: id ? 'PUT' : 'POST', body });
      closeForm(); await load(); notice(id ? 'Item saved.' : 'Item added.'); }
    catch (e) { if (e.status === 401) { setOwner(false); showLogin('Your session expired. Sign in again, then press Save.'); } else { err.textContent = e.message; err.hidden = false; } }  // the form keeps the user's input on failure
    finally { busy = false; btn.disabled = false; }
  });

  syncOwnerUi();
  api('/api/owner/me').then((m) => { if (m.restaurant_id === rid) setOwner(true); }).catch(() => setOwner(false)).finally(load);
})();
