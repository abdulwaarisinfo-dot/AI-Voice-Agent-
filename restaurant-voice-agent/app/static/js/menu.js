/* Menu page: shows the menu from the API. Everyone sees Add / Edit / Delete / Mark unavailable;
   if the owner is not signed in, clicking one opens the login and then carries on with that action.
   The server still enforces the owner session on every change. */
(() => {
  'use strict';
  const root = document.getElementById('menu-root');
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const rid = root.dataset.restaurantId;
  let currency = 'PKR', items = [], owner = false, busy = false, pending = null, loginOpen = false, query = '', activeCat = '';

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
  // No photos: each dish and category gets a soft emoji tile chosen from its name (safe, widely supported emoji only).
  const GLYPHS = [
    [/pizza/, '\u{1F355}'], [/fries|chips/, '\u{1F35F}'], [/sandwich|club|wrap|sub\b/, '\u{1F96A}'],
    [/burger|zinger|fast ?food/, '\u{1F354}'], [/biryani|pulao|pilau|rice|zeera|chawal/, '\u{1F35A}'],
    [/naan|roti|paratha|bread|kulcha|chapati/, '\u{1F959}'], [/pakora|fritter/, '\u{1F9C6}'],
    [/samosa|spring roll|starter|appetizer|snack/, '\u{1F95F}'], [/soup|shorba/, '\u{1F963}'],
    [/chicken tikka|fried chicken|broast|chargha|wings/, '\u{1F357}'], [/tikka|kabab|kebab|bbq|boti|grill|tandoor|seekh|steak/, '\u{1F356}'],
    [/karahi|handi|curry|korma|qorma|nihari|haleem|mains?|daal|dal\b|lentil|masala|gravy|sabzi/, '\u{1F35B}'],
    [/lassi|juice|drink|soda|shake|chai|tea\b|coffee|water|cola|mojito|lime|beverage/, '\u{1F964}'],
    [/kheer|gulab|jamun|dessert|sweet|ice ?cream|cake|halwa|kulfi|falooda|pudding/, '\u{1F36E}'],
    [/salad/, '\u{1F957}'], [/fish|prawn|shrimp|sea ?food/, '\u{1F990}'], [/pasta|noodle|spaghetti|chow ?mein/, '\u{1F35D}'],
  ];
  const glyphOf = (text) => { const t = String(text || '').toLowerCase(); const m = GLYPHS.find(([re]) => re.test(t)); return m ? m[1] : null; };
  const dishGlyph = (i) => glyphOf(i.name) || glyphOf(i.category) || '\u{1F37D}\uFE0F';
  const catGlyph = (c) => glyphOf(c) || dishGlyph(items.find((i) => i.category === c) || { name: '', category: '' });

  function renderChips(cats) {
    const box = $('cat-chips'); box.replaceChildren();
    box.hidden = cats.length < 2;                                   // a single category needs no filter
    const make = (value, glyph, label) => {
      const b = el('button', 'cat'); b.type = 'button'; b.setAttribute('aria-pressed', String(activeCat === value));
      b.append(el('span', 'disc', glyph), el('span', '', label));
      b.onclick = () => { activeCat = value; render(); }; return b;
    };
    box.appendChild(make('', '\u{1F37D}\uFE0F', 'All'));
    cats.forEach((c) => box.appendChild(make(c, catGlyph(c), c)));
  }

  function render() {
    const list = $('menu-list'); list.replaceChildren();
    const cats = [...new Set(items.map((i) => i.category))];
    if (activeCat && !cats.includes(activeCat)) activeCat = '';
    $('cat-list').replaceChildren(...cats.map((c) => { const o = document.createElement('option'); o.value = c; return o; }));
    renderChips(cats);
    if (!items.length) { notice('The menu is empty. Click "+ Add new item" to add your first dish.'); return; }
    const q = query.trim().toLowerCase();
    const shown = items.filter((i) => (!activeCat || i.category === activeCat) &&
      (!q || (i.name + ' ' + i.description + ' ' + i.category).toLowerCase().includes(q)));
    if (!shown.length) {
      const box = el('div', 'empty', q ? 'No dishes match "' + query.trim() + '".' : 'No dishes in this category.');
      const clear = button('Show all dishes', 'btn small', () => { query = ''; activeCat = ''; $('menu-search').value = ''; render(); });
      box.append(document.createElement('br'), clear); list.appendChild(box);
      notice('0 of ' + items.length + ' dishes shown.'); return;
    }
    const filtered = shown.length !== items.length;
    notice(filtered ? shown.length + ' of ' + items.length + ' dishes shown.'
      : items.length + (items.length === 1 ? ' dish' : ' dishes') + ' in ' + cats.length + (cats.length === 1 ? ' category' : ' categories') + '.');
    cats.forEach((cat, ci) => {
      const inCat = shown.filter((i) => i.category === cat); if (!inCat.length) return;
      list.appendChild(el('h2', '', cat));
      const grid = el('div', 'grid');
      inCat.forEach((i) => {
        const card = el('article', 'card' + (i.available ? '' : ' off'));
        card.appendChild(el('div', 'tile t' + (ci % 5), dishGlyph(i)));
        const main = el('div', 'card-main');
        const top = el('div', 'name-row'); top.append(el('h3', '', i.name), el('div', 'price', i.price)); main.appendChild(top);
        if (i.description) main.appendChild(el('p', 'desc', i.description));
        if (i.options.length) main.appendChild(el('p', 'opts', 'Options: ' + i.options.join(', ')));
        if (!i.available) main.appendChild(el('span', 'badge off', 'Unavailable'));
        card.appendChild(main);
        const actions = el('div', 'actions');
        actions.append(
          button('Edit', 'btn small', () => asOwner(() => openForm(i))),
          button(i.available ? 'Mark unavailable' : 'Mark available', 'btn small', () => asOwner(() => toggle(i))),
          button('Delete', 'btn small danger', () => asOwner(() => remove(i))));
        card.appendChild(actions); grid.appendChild(card);
      });
      list.appendChild(grid);
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
  $('menu-search').addEventListener('input', (ev) => { query = ev.target.value; render(); });
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
