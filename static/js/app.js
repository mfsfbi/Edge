const qs=(s,r=document)=>r.querySelector(s);
const qsa=(s,r=document)=>[...r.querySelectorAll(s)];
const menu=qs('.menu-btn'), drawer=qs('.mobile-drawer');
if(menu&&drawer){menu.addEventListener('click',()=>{const open=drawer.classList.toggle('show');menu.setAttribute('aria-expanded',String(open));});}
const panel=qs('[data-chat-panel]'), trigger=qs('.chat-trigger'), close=qs('.chat-close');
function toggleChat(){const open=panel?.classList.toggle('open');trigger?.setAttribute('aria-expanded',String(!!open));}
if(trigger) trigger.addEventListener('click',toggleChat); if(close) close.addEventListener('click',toggleChat);
const form=qs('[data-chat-form]');
if(form){form.addEventListener('submit',async(e)=>{e.preventDefault();const input=qs('input',form), msg=input.value.trim();if(!msg)return;const body=qs('[data-chat-body]');const me=document.createElement('div');me.className='bubble me';me.textContent=msg;body.appendChild(me);input.value='';body.scrollTop=body.scrollHeight;try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})});const d=await r.json();const bot=document.createElement('div');bot.className='bubble bot';bot.textContent=d.reply;body.appendChild(bot);}catch{const bot=document.createElement('div');bot.className='bubble bot';bot.textContent='For immediate help, call us or tap WhatsApp.';body.appendChild(bot);}body.scrollTop=body.scrollHeight;});}
if(window.lucide) window.lucide.createIcons();
const map=qs('#intex-map');
if(map){const lat=Number(map.dataset.lat||-1.2921),lng=Number(map.dataset.lng||36.8219),label=map.dataset.label||'INTEX Pest Limited';const iframe=document.createElement('iframe');iframe.loading='lazy';iframe.referrerPolicy='no-referrer-when-downgrade';iframe.title='Map to INTEX Pest Limited';const d=0.02;iframe.src=`https://www.openstreetmap.org/export/embed.html?bbox=${lng-d}%2C${lat-d}%2C${lng+d}%2C${lat+d}&layer=mapnik&marker=${lat}%2C${lng}`;map.appendChild(iframe);const pin=document.createElement('div');pin.className='map-pin';pin.innerHTML=`<span></span><strong>${label}</strong>`;map.appendChild(pin);}
if('serviceWorker' in navigator) window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{}));

const revealItems=qsa('.service-grid-v2 article,.proof-card,.kpi-v2,.workspace-card,.hero-core');
if('IntersectionObserver' in window){const io=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){e.target.classList.add('is-visible');io.unobserve(e.target);}}),{threshold:.08});revealItems.forEach(e=>{e.classList.add('reveal');io.observe(e);});}
