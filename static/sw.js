const CACHE='tthms-v1';
const ASSETS=['/dashboard','/static/style.css','/static/manifest.json'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS))));
self.addEventListener('fetch',e=>e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(res=>{const copy=res.clone(); if(e.request.method==='GET') caches.open(CACHE).then(c=>c.put(e.request,copy)); return res;}).catch(()=>caches.match('/dashboard')))));
