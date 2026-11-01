// Runs the REAL app/static/js/chat.js against fakes for the DOM and fetch.
// Run with:  node --test tests/frontend/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const SRC = fs.readFileSync(new URL('../../app/static/js/chat.js', import.meta.url), 'utf8');
const REDIRECT_DELAY_MS = 2500;   // must match REDIRECT_DELAY_MS in chat.js (mapped to a short delay below)
const flush = async (n = 12) => { for (let i = 0; i < n; i++) await new Promise((r) => setImmediate(r)); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const bad = (status, body = {}) => ({ ok: false, status, json: async () => body });
const ORDER = { reference: 'ORD-ABCDEFGH', url: '/confirmation/ORD-ABCDEFGH?t=tok' };

function harness({ route, restaurantId = 'resto-a' } = {}) {
  const ids = ['chat-root', 'chat-log', 'chat-form', 'chat-input', 'chat-send', 'chat-typing', 'chat-error',
    'order-banner', 'order-text', 'order-link', 'chat-new'];
  const els = {};
  for (const id of ids) {
    const l = {};
    els[id] = { id, hidden: false, disabled: false, textContent: '', value: '', className: '', dataset: {}, children: [], scrollTop: 0, scrollHeight: 0,
      addEventListener(t, f) { (l[t] ||= []).push(f); }, fire(t, ev = {}) { (l[t] || []).forEach((f) => f(ev)); },
      appendChild(c) { this.children.push(c); return c; }, setAttribute() {}, focus() { this.focused = true; } };
  }
  els['chat-root'].dataset = { restaurantId };
  for (const id of ['order-banner', 'chat-error', 'chat-typing']) els[id].hidden = true;   // as in chat.html
  const log = { fetch: [], locations: [] };
  const sandbox = {
    console, JSON, Uint8Array, Array, Error, Promise,
    setTimeout: (f, ms) => { const t = setTimeout(f, ms === REDIRECT_DELAY_MS ? 300 : ms); t.unref?.(); return t; }, clearTimeout,
    crypto: { getRandomValues: (b) => { for (let i = 0; i < b.length; i++) b[i] = Math.floor(Math.random() * 256); return b; } },
    document: { getElementById: (id) => els[id] || null,
      createElement: () => ({ className: '', textContent: '', children: [], appendChild(c) { this.children.push(c); return c; }, setAttribute() {} }) },
    location: { assign: (u) => log.locations.push(u), reload: () => log.locations.push('RELOAD') },
    fetch: async (path, init = {}) => {
      const entry = { path, method: init.method || 'GET', headers: init.headers || {}, body: init.body ? JSON.parse(init.body) : null };
      log.fetch.push(entry);
      return (route && route(entry)) ?? defaultRoute(entry);
    },
  };
  const defaultRoute = (e) => {
    if (e.path === '/api/chat/session') return ok({ chat_secret: 'sec', greeting: 'hi' });
    if (e.path === '/api/chat/message') return ok({ reply: 'Sure!', order: null });
    return ok({ ok: true });
  };
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);
  const send = async (text) => { els['chat-input'].value = text; els['chat-form'].fire('submit', { preventDefault() {} }); await flush(); };
  return { els, log, send, paths: () => log.fetch.map((f) => f.path),
    lines: () => els['chat-log'].children.map((ln) => ln.children[1].textContent) };
}

test('confirmed order: the reply is shown, then the customer is taken to the confirmation page exactly once', async () => {
  const h = harness({ route: (e) => (e.path === '/api/chat/message' ? ok({ reply: 'Placed! Reference ORD-ABCDEFGH', order: ORDER }) : undefined) });
  await h.send('yes, confirm');
  assert.deepEqual(h.lines(), ['yes, confirm', 'Placed! Reference ORD-ABCDEFGH']);   // customer can read the final message first
  assert.equal(h.els['order-banner'].hidden, false);
  assert.match(h.els['order-text'].textContent, /ORD-ABCDEFGH/);
  assert.equal(h.els['order-link'].href, ORDER.url);                                   // fallback link
  assert.deepEqual(h.log.locations, []);                                               // not instant
  await sleep(450); await flush();
  assert.deepEqual(h.log.locations, [ORDER.url]);                                      // the server-provided url, once
  assert.equal(h.els['chat-input'].disabled, true); assert.equal(h.els['chat-send'].disabled, true);   // chat is finished
  assert.ok(h.paths().every((p) => p.startsWith('/api/chat/')), 'browser must only call /api/chat/*: ' + h.paths());
});

test('no confirmed order: the chat stays open and nothing navigates', async () => {
  const h = harness();
  await h.send('delivery please');
  await sleep(450); await flush();
  assert.deepEqual(h.log.locations, []);
  assert.equal(h.els['order-banner'].hidden, true); assert.equal(h.els['order-text'].textContent, '');
  assert.equal(h.els['chat-input'].disabled, false);
  assert.deepEqual(h.lines(), ['delivery please', 'Sure!']);
});

test('a failed message never navigates', async () => {
  const h = harness({ route: (e) => (e.path === '/api/chat/message' ? bad(502, { detail: 'Chat is unavailable right now. Please try again.' }) : undefined) });
  await h.send('yes');
  await sleep(450); await flush();
  assert.deepEqual(h.log.locations, []);
  assert.match(h.els['chat-error'].textContent, /unavailable/i);
});

test('the browser never sends an order, price, address or confirmation itself: only the typed text', async () => {
  const h = harness();
  await h.send('Deliver to 12 Canal Road, Gulberg');
  const msg = h.log.fetch.find((f) => f.path === '/api/chat/message');
  assert.deepEqual(Object.keys(msg.body).sort(), ['client_chat_id', 'message']);
  assert.equal(msg.body.message, 'Deliver to 12 Canal Road, Gulberg');
  assert.equal(msg.headers['X-Chat-Secret'], 'sec');
});
