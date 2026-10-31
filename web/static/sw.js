// Service Worker: deixa o Nexus instalável e mostra as notificações do sistema
// (app/push.py), mesmo com o app fechado. Sem handler de 'fetch': tudo vai pela
// rede, sem risco de servir versão obsoleta (o cache continua no nginx).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

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
