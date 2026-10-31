// Service Worker: deixa o Nexus instalável, mostra as notificações do sistema
// (app/push.py), mesmo com o app fechado, recebe o "compartilhar" de outros
// apps e segura o app sem sinal. Rede primeiro, sempre: com conexão, tudo vem
// do servidor (nada de versão velha); a cópia guardada só aparece quando a rede
// falha — e a resposta da API vem marcada (X-Nexus-Cache) para a tela avisar.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

// Compartilhar de outro app (share_target POST com fotos): guarda texto e fotos
// no cache do aparelho e abre o app, que monta a nova tarefa (mesmo que precise
// entrar antes). Até 10 fotos.
const SHARE = 'nexus-compartilhado';
const CASCO = 'nexus-casco';   // páginas, CSS, JS, fontes, ícones
const DADOS = 'nexus-dados';   // as últimas leituras das telas principais
// Leituras que valem sem sinal (as de abrir o dia). Relatórios, busca e admin, não.
const API_OK = /^\/api\/(auth\/me|board|projects|branding|timer|recurring\/reminders|summary(\/[a-z]+)?|renewals|worklog\/\d+)$/;

async function networkFirst(req, cacheName, timeout, mark) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req, { signal: AbortSignal.timeout(timeout) });
    if (res.ok && res.type === 'basic') cache.put(req, res.clone());
    return res;
  } catch (e) {
    const hit = (await cache.match(req)) || (req.mode === 'navigate' ? await cache.match('/') : null);
    if (!hit) throw e;
    if (!mark) return hit;
    const headers = new Headers(hit.headers);
    headers.set('X-Nexus-Cache', hit.headers.get('Date') || new Date().toUTCString());
    return new Response(hit.body, { status: hit.status, headers });
  }
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (req.method === 'GET') {
    if (url.pathname.startsWith('/api/')) {
      if (API_OK.test(url.pathname)) event.respondWith(networkFirst(req, DADOS, 8000, true));
      return;  // o resto da API: só rede
    }
    if (url.pathname === '/login' || url.pathname === '/sw.js') return;
    event.respondWith(networkFirst(req, CASCO, 10000, false));
    return;
  }
  if (req.method !== 'POST' || url.pathname !== '/compartilhar') return;
  event.respondWith((async () => {
    const form = await event.request.formData();
    const cache = await caches.open(SHARE);
    for (const k of await cache.keys()) await cache.delete(k);
    const fotos = form.getAll('fotos').filter((f) => f && f.size && /^image\//.test(f.type)).slice(0, 10);
    await cache.put('/compartilhado/dados', new Response(JSON.stringify({
      title: form.get('title') || '', text: form.get('text') || '', url: form.get('url') || '', fotos: fotos.length })));
    for (const [i, f] of fotos.entries()) await cache.put(`/compartilhado/foto-${i}`, new Response(f, { headers: { 'Content-Type': f.type } }));
    return Response.redirect('/?compartilhado=1', 303);
  })());
});

// O conteúdo chega criptografado e o navegador entrega já aberto: {title, body,
// url, tag, kind, actions?, id?, day?, require_interaction?}.
self.addEventListener('push', (event) => {
  let msg = {};
  try { msg = event.data ? event.data.json() : {}; } catch { msg = { title: 'Nexus', body: event.data && event.data.text() }; }
  const title = msg.title || 'Nexus';
  const options = {
    body: msg.body || '',
    tag: msg.tag,
    renotify: !!msg.tag,                       // a repetição da rotina toca de novo
    requireInteraction: !!msg.require_interaction,
    icon: '/img/icon-192.png',
    badge: '/img/badge-96.png',                // a silhueta na barra do Android
    actions: msg.actions || [],
    data: { url: msg.url || '/#/hoje', kind: msg.kind, id: msg.id, day: msg.day },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

// A sessão do aparelho vale aqui também (mesmo site); o CSRF vem do /auth/me.
async function call(path, body) {
  const me = await fetch('/api/auth/me', { credentials: 'same-origin' });
  if (!me.ok) throw new Error('sem sessão');
  const { csrf_token: csrf } = await me.json();
  const res = await fetch('/api' + path, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error('falhou');
}

async function openApp(url) {
  const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  for (const w of wins) {
    if (new URL(w.url).origin === self.location.origin) {
      await w.focus();
      return w.navigate ? w.navigate(url).catch(() => w) : w;
    }
  }
  return self.clients.openWindow(url);
}

self.addEventListener('notificationclick', (event) => {
  const n = event.notification;
  const d = n.data || {};
  n.close();
  event.waitUntil((async () => {
    try {
      if (event.action === 'feita' && d.kind === 'rotina') {
        await call(`/recurring/${d.id}/toggle`, { done: true, day: d.day });
        return;
      }
      if (event.action === 'adiar' && d.kind === 'rotina') {
        await call(`/recurring/${d.id}/snooze`, { minutes: 10 });
        return;
      }
    } catch {
      // Sem sessão (saiu, senha trocada) ou sem rede: abre o app, que resolve.
    }
    await openApp(d.url || '/#/hoje');
  })());
});
