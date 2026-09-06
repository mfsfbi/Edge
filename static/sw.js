const CACHE='intex-v1';
const ASSETS=['/','/services','/contact','/visit','/static/css/app.css','/static/js/app.js','/static/uploads/logo.svg'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS))));
self.addEventListener('fetch',e=>{if(e.request.method==='GET') e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(n=>{const c= n.clone(); caches.open(CACHE).then(x=>x.put(e.request,c)); return n;}).catch(()=>caches.match('/'))))});
