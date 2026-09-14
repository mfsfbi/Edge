const CACHE='o-v3';
const CORE=['/','/static/app.js','/static/manifest.json','/static/icon-192.png','/static/icon-512.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(c=>c.addAll(CORE)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{if(event.request.method!=='GET')return;event.respondWith(caches.match(event.request).then(cached=>cached||fetch(event.request).then(resp=>{if(new URL(event.request.url).origin===self.location.origin){const copy=resp.clone();caches.open(CACHE).then(c=>c.put(event.request,copy)).catch(()=>{})}return resp}).catch(()=>caches.match('/'))));});
