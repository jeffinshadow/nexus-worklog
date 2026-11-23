// Service Worker: deixa o Nexus instalável, mostra as notificações do sistema
// (app/push.py), mesmo com o app fechado, recebe o "compartilhar" de outros
// apps e segura o app sem sinal. Rede primeiro: com conexão, tudo vem do
// servidor (nada de versão velha); a cópia guardada só aparece quando a rede
// falha, demora demais ou o servidor está fora (502, 503, 504) — e a resposta
// da API vem marcada (X-Nexus-Cache) para a tela avisar.
// Duas exceções, as duas só depois de a rede falhar:
// - Sinal fraco: depois de um estouro de TEMPO da página ou de uma leitura (não
//   de erro rápido), as duas esperam a rede só 1,5 s durante 60 s; a primeira
//   resposta do servidor, ou o fim dos 60 s, devolve a espera normal.
// - Quando a página veio da cópia guardada, o resto do app (CSS, JS, fontes)
//   vem da cópia nessa abertura: os módulos se importam sem versão na URL, e
//   misturar rede e cópia logo depois de uma atualização quebraria o app.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

// Compartilhar de outro app (share_target POST com fotos): guarda texto e fotos
// no cache do aparelho e abre o app, que monta a nova tarefa (mesmo que precise
// entrar antes). Até 10 fotos.
const SHARE = 'nexus-compartilhado';
const CASCO = 'nexus-casco';   // páginas, CSS, JS, fontes, ícones
const DADOS = 'nexus-dados';   // as últimas leituras das telas principais
// Leituras que valem sem sinal (as de abrir o dia). Relatórios, busca e admin, não.
const API_OK = /^\/api\/(auth\/me|board|projects(\/\d+\/overview)?|branding|timer|recurring\/reminders|summary(\/[a-z]+)?|renewals|worklog\/\d+)$/;

// Arquivo com versão na URL (app.js?v=168): ao guardar a nova, a cópia da versão
// anterior sai (senão cada atualização deixava mais um jogo de arquivos no aparelho).
async function dropOldVersions(cache, req) {
  const url = new URL(req.url);
  if (!url.searchParams.has('v')) return;
  // Só quando quem pediu foi o próprio app ("/"): o login e a página 404 usam os mesmos arquivos,
  // e apagar por causa deles deixaria o "/" guardado (ainda da versão anterior) sem CSS, se abrisse sem sinal.
  let from = '';
  try { from = new URL(req.referrer).pathname; } catch { /* sem referrer: não apaga */ }
  if (from !== '/') return;
  for (const k of await cache.keys()) {
    const u = new URL(k.url);
    if (u.pathname === url.pathname && u.search !== url.search) await cache.delete(k);
  }
}

const CURTA = 1500, LENTO_POR = 60000;
let lentoAte = 0;            // até quando a espera é a curta (o último pedido estourou o tempo)
const daCopia = new Set();   // aberturas (id da página) em que a página veio da cópia guardada
const espera = (normal) => (Date.now() < lentoAte ? CURTA : normal);

// onCopy: chamada quando a resposta sai da cópia guardada.
async function networkFirst(req, cacheName, timeout, mark, onCopy) {
  const cache = await caches.open(cacheName);
  let fora = null;
  try {
    const res = await fetch(req, { signal: AbortSignal.timeout(timeout) });
    lentoAte = 0;  // o servidor (ou o proxy) respondeu: a rede está viva
    // Servidor reiniciando ou fora atrás do proxy: vale a cópia guardada, como sem rede.
    if (res.status >= 502 && res.status <= 504) { fora = res; throw new Error('servidor fora'); }
    if (res.ok && res.type === 'basic') {
      cache.put(req, res.clone()).then(() => dropOldVersions(cache, req)).catch(() => {});  // cota cheia: segue sem guardar
    }
    return res;
  } catch (e) {
    const hit = (await cache.match(req)) || (req.mode === 'navigate' ? await cache.match('/') : null);
    // Só a espera cheia da página ou de uma leitura liga a espera curta: se a curta também ligasse, uma rede
    // lenta mas viva (resposta em 2 a 5 s) ficaria presa na cópia para sempre. Passados os 60 s, o próximo
    // pedido espera o tempo normal de novo e decide.
    if (e && e.name === 'TimeoutError' && timeout > CURTA && (mark || req.mode === 'navigate')) lentoAte = Date.now() + LENTO_POR;
    if (!hit) { if (fora) return fora; throw e; }
    if (onCopy) onCopy();
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
      // A abertura (auth/me) desiste antes: o app espera 6,5 s por ela e a cópia guardada precisa chegar antes disso.
      if (API_OK.test(url.pathname)) event.respondWith(networkFirst(req, DADOS, espera(url.pathname === '/api/auth/me' ? 5000 : 8000), true));
      return;  // o resto da API: só rede
    }
    if (url.pathname === '/login' || url.pathname === '/sw.js') return;
    if (req.mode === 'navigate') {
      const id = event.resultingClientId;
      event.respondWith(networkFirst(req, CASCO, espera(10000), false, () => {
        if (!id) return;
        if (daCopia.size > 30) daCopia.clear();
        daCopia.add(id);
      }));
      return;
    }
    // A página desta abertura veio da cópia: o resto vem de lá também (só o que faltar vai à rede).
    if (event.clientId && daCopia.has(event.clientId)) {
      event.respondWith(caches.open(CASCO).then((c) => c.match(req)).then((hit) => hit || networkFirst(req, CASCO, 10000, false)));
      return;
    }
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
      // Lembrete com hora de uma tarefa ("Lembrar em"): Concluir e Adiar direto da notificação.
      if (event.action === 'concluir' && d.kind === 'lembrete') {
        await call(`/worklog/${d.id}/finish`, {});
        return;
      }
      if (event.action === 'adiar' && d.kind === 'lembrete') {
        await call(`/worklog/${d.id}/snooze`, { minutes: 10 });
        return;
      }
    } catch {
      // Sem sessão (saiu, senha trocada) ou sem rede: abre o app, que resolve.
    }
    await openApp(d.url || '/#/hoje');
  })());
});
