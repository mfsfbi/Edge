const qs=(s,r=document)=>r.querySelector(s);
const qsa=(s,r=document)=>[...r.querySelectorAll(s)];
const menu=qs('.menu-btn'), drawer=qs('.mobile-drawer');
const setMenu=(open)=>{
  if(!menu||!drawer)return;
  drawer.classList.toggle('show',open);
  menu.setAttribute('aria-expanded',String(open));
  menu.setAttribute('aria-label',open?'Close menu':'Open menu');
  const icon=qs('svg',menu);
  if(icon){icon.remove(); const el=document.createElement('i'); el.setAttribute('data-lucide',open?'x':'menu'); menu.prepend(el); if(window.lucide)window.lucide.createIcons();}
};
if(menu&&drawer){
  menu.addEventListener('click',(e)=>{e.stopPropagation();setMenu(!drawer.classList.contains('show'));});
  qsa('.mobile-drawer a').forEach(a=>a.addEventListener('click',()=>setMenu(false)));
  document.addEventListener('click',(e)=>{if(drawer.classList.contains('show')&&!drawer.contains(e.target)&&!menu.contains(e.target))setMenu(false);});
  document.addEventListener('keydown',(e)=>{if(e.key==='Escape')setMenu(false);});
  window.addEventListener('resize',()=>{if(window.innerWidth>760)setMenu(false);});
}
const map=qs('#intex-map');
if(map){const lat=Number(map.dataset.lat||-1.2921),lng=Number(map.dataset.lng||36.8219),label=map.dataset.label||'INTEX — Nairobi, Kenya';const iframe=document.createElement('iframe');iframe.loading='lazy';iframe.referrerPolicy='no-referrer-when-downgrade';iframe.title='Map to INTEX';const d=0.02;iframe.src=`https://www.openstreetmap.org/export/embed.html?bbox=${lng-d}%2C${lat-d}%2C${lng+d}%2C${lat+d}&layer=mapnik&marker=${lat}%2C${lng}`;map.appendChild(iframe);const pin=document.createElement('div');pin.className='map-pin';pin.innerHTML=`<span></span><strong>${label}</strong>`;map.appendChild(pin);}
if('serviceWorker' in navigator) window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{}));
const revealItems=qsa('.service-grid-v2 article,.pharma-card,.timeline-card,.product-grid article,.material-grid>div,.lab-step,.quality-stack>div,.hero-core');
if('IntersectionObserver' in window){const io=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){e.target.classList.add('is-visible');io.unobserve(e.target);}}),{threshold:.08});revealItems.forEach(e=>{e.classList.add('reveal');io.observe(e);});}
const shareQr=qs('[data-share-qr]');
if(shareQr){shareQr.addEventListener('click',async()=>{const data={title:'INTEX Visitor Check-in',text:'Facility visitor check-in',url:new URL('/visit',location.origin).href};try{if(navigator.share){await navigator.share(data);}else if(navigator.clipboard){await navigator.clipboard.writeText(data.url);shareQr.innerHTML='<i data-lucide="check"></i> Link copied';if(window.lucide)window.lucide.createIcons();}}catch(e){}});}

// INTEX activity-zone navigation: switches panels without browser hash jumps.
const zoneLinks=qsa('.zone-link[data-zone]');
const zonePanels=qsa('.zone-panel[data-panel]');
const openZone=(zone, updateUrl=true)=>{
  if(!zonePanels.length)return;
  const target=zonePanels.some(p=>p.dataset.panel===zone)?zone:'overview';
  zonePanels.forEach(p=>p.classList.toggle('active',p.dataset.panel===target));
  zoneLinks.forEach(b=>b.classList.toggle('active',b.dataset.zone===target));
  if(updateUrl){
    const u=new URL(location.href); u.searchParams.set('zone',target); history.replaceState(null,'',u.pathname+'?'+u.searchParams.toString());
  }
};
zoneLinks.forEach(b=>b.addEventListener('click',()=>openZone(b.dataset.zone)));
qsa('[data-zone-open]').forEach(b=>b.addEventListener('click',()=>openZone(b.dataset.zoneOpen)));
if(zonePanels.length){const initial=new URLSearchParams(location.search).get('zone');openZone(initial||'overview',false);}
qsa('.reference-pill[data-product]').forEach(btn=>btn.addEventListener('click',()=>{
  const input=qs('input[name="product"]',btn.closest('.workspace-card'));
  if(input){input.value=btn.dataset.product;input.focus();}
}));
