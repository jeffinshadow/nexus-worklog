// Service Worker minimo: habilita a instalacao como PWA sem cache offline.
// Sem handler de 'fetch' (o Chrome não exige mais): tudo vai pela rede, sem
// risco de servir versao obsoleta (cache continua no nginx).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
