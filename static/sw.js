const CACHE='o-shell-v2';
const ASSETS=['/','/app','/people','/login','/register','/robots.txt','/sitemap.xml','/static/css/o.css','/static/js/o.js','/static/manifest.json','/static/icons/o.svg','/static/icons/favicon-48.png','/static/icons/o-192.png','/static/icons/o-512.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS).catch(()=>{})).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{if(event.request.method!=='GET')return; event.respondWith(fetch(event.request).then(response=>{const copy=response.clone(); caches.open(CACHE).then(cache=>cache.put(event.request,copy)).catch(()=>{}); return response;}).catch(()=>caches.match(event.request).then(response=>response||caches.match('/'))));});
