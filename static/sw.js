const CACHE='intex-v3';
const STATIC_ASSETS=['/static/css/app.css','/static/js/app.js','/static/uploads/logo.svg'];

self.addEventListener('install', event=>{
  event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(STATIC_ASSETS)).then(()=>self.skipWaiting()));
});

self.addEventListener('activate', event=>{
  event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim()));
});

self.addEventListener('fetch', event=>{
  if(event.request.method!=='GET') return;
  const request=event.request;
  const isNavigation=request.mode==='navigate';
  event.respondWith(
    fetch(request).then(response=>{
      if(response.ok && !isNavigation){
        const copy=response.clone();
        caches.open(CACHE).then(cache=>cache.put(request,copy));
      }
      return response;
    }).catch(()=>caches.match(request).then(cached=>cached || (isNavigation ? caches.match('/') : Response.error())))
  );
});
