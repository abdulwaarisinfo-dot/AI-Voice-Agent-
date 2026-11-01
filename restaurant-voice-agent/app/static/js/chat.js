/* Browser side of the text chat. No microphone, no WebRTC, no GPT-Live.
 *
 *   1. The greeting is rendered by the server. No session exists until the first message is sent.
 *   2. First send:  POST /api/chat/session  -> chat_secret   (the browser makes up a 32-hex chat id)
 *   3. Every send:  POST /api/chat/message  (X-Chat-Secret)  -> { reply, order }
 *   4. When `order` comes back the order is confirmed by the SERVER; we show its link and, after a short pause so
 *      the customer can read the assistant's last message, open the confirmation page.
 * All text is inserted with textContent (never innerHTML).
 */
(() => {
  'use strict';
  const root = document.getElementById('chat-root');
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const el = {
    log: $('chat-log'), form: $('chat-form'), input: $('chat-input'), send: $('chat-send'), typing: $('chat-typing'),
    error: $('chat-error'), banner: $('order-banner'), bannerText: $('order-text'), link: $('order-link'), fresh: $('chat-new'),
  };
  const cfg = { restaurantId: root.dataset.restaurantId };
  const configured = () => typeof cfg.restaurantId === 'string' && cfg.restaurantId.trim() !== '';
  const REDIRECT_DELAY_MS = 2500;

  let chatId = null, secret = null, busy = false, finished = false;

  const randomId = () => {
    const b = new Uint8Array(16); crypto.getRandomValues(b);
    return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  };

  function showError(msg) { el.error.textContent = msg; el.error.hidden = !msg; }

  function setBusy(on) {
    busy = on;
    el.typing.hidden = !on;
    el.send.disabled = on || finished;
    el.input.disabled = finished;
  }

  function addLine(role, label, text) {
    const line = document.createElement('p');
    line.className = 'line ' + role;
    const who = document.createElement('span'); who.className = 'who'; who.textContent = label + ':';
    const body = document.createElement('span'); body.className = 'msg'; body.setAttribute('dir', 'auto'); body.textContent = text;
    line.appendChild(who); line.appendChild(body);
    el.log.appendChild(line);
    el.log.scrollTop = el.log.scrollHeight;
  }

  function describe(err) {
    if (err && err.status === 429) return err.detail || 'Too many messages. Please wait a moment and try again.';
    if (err && err.status === 404) return 'This chat expired, so your last message was not sent. Press "Start a new chat" and send it again.';
    if (err && err.status === 409) return err.detail || 'This chat is finished. Start a new chat.';
    if (err && err.status === 503) return (err.detail || 'Chat is unavailable right now.') + ' You can still browse the menu.';
    if (err && err.status) return 'Chat is unavailable right now (error ' + err.status + '). You can still browse the menu.';
    if (err && err.name === 'TypeError') return 'Network error. Check your connection and try again.';
    return 'Something went wrong. Please try again.';
  }

  async function api(path, body, withSecret) {
    const headers = { 'Content-Type': 'application/json' };
    if (withSecret && secret) headers['X-Chat-Secret'] = secret;
    const res = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body), credentials: 'same-origin' });
    if (!res.ok) {
      const err = new Error('http'); err.status = res.status;
      try { err.detail = (await res.json()).detail; } catch (_) { /* ignore */ }
      throw err;
    }
    return res.json();
  }

  async function ensureSession() {
    if (secret) return;
    chatId = chatId || randomId();
    const res = await api('/api/chat/session', { client_chat_id: chatId, restaurant_id: cfg.restaurantId }, false);
    secret = res.chat_secret;
  }

  function showOrder(order) {
    finished = true;
    el.bannerText.textContent = 'Your order is confirmed. Reference: ' + order.reference;
    el.link.href = order.url;
    el.banner.hidden = false;
    setTimeout(() => location.assign(order.url), REDIRECT_DELAY_MS);   // the banner link stays as the fallback
  }

  async function submit(ev) {
    if (ev) ev.preventDefault();
    if (busy || finished || !configured()) return;
    const text = el.input.value.trim();
    if (!text) return;
    showError('');
    addLine('you', 'You', text);
    el.input.value = '';
    setBusy(true);
    try {
      await ensureSession();
      const res = await api('/api/chat/message', { client_chat_id: chatId, message: text }, true);
      addLine('assistant', 'Assistant', res.reply);
      if (res.order) showOrder(res.order);
    } catch (err) {
      if (err && err.status === 404) { secret = null; chatId = null; }   // server forgot this chat: next send starts a fresh one
      showError(describe(err));
    } finally {
      setBusy(false);
      if (!finished) el.input.focus();
    }
  }

  function startNew() {
    if (secret && chatId) {                                            // best effort: free the server slot
      fetch('/api/chat/end', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Chat-Secret': secret },
        body: JSON.stringify({ client_chat_id: chatId }), keepalive: true, credentials: 'same-origin' }).catch(() => {});
    }
    location.reload();                                                 // fresh greeting, fresh id, no old order link
  }

  el.form.addEventListener('submit', submit);
  el.fresh.addEventListener('click', startNew);
  setBusy(false);
  if (!configured()) { el.input.disabled = true; el.send.disabled = true; }
})();
