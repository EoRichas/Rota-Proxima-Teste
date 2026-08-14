const CACHE='rota-proxima-teste-browser-sync-20260814-v1';
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
