const $=(s)=>document.querySelector(s);
const nav=document.querySelector('.nav'); const menu=$('.mobile-menu button');
if(menu) menu.addEventListener('click',()=>nav.classList.toggle('mobile-open'));
const chat=$('.chat'); const chatBtn=$('.chat-trigger');
if(chatBtn) chatBtn.addEventListener('click',()=>chat.classList.toggle('open'));
const close=$('.chat-close'); if(close) close.addEventListener('click',()=>chat.classList.remove('open'));
const form=$('.chat-input');
if(form){form.addEventListener('submit',async(e)=>{e.preventDefault();const input=form.querySelector('input');const msg=input.value.trim();if(!msg)return;const body=$('.chat-body');body.insertAdjacentHTML('beforeend',`<div class="bubble me"></div>`);body.lastElementChild.textContent=msg;input.value='';try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})});const d=await r.json();body.insertAdjacentHTML('beforeend',`<div class="bubble bot"></div>`);body.lastElementChild.textContent=d.reply;body.scrollTop=body.scrollHeight}catch{body.insertAdjacentHTML('beforeend','<div class="bubble bot">Please call us directly for immediate assistance.</div>')}})}
const geo=document.querySelector('[data-geo]');
if(geo && navigator.geolocation) navigator.geolocation.getCurrentPosition(p=>geo.dataset.geo=`${p.coords.latitude.toFixed(5)}, ${p.coords.longitude.toFixed(5)}`);
if('serviceWorker' in navigator) window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{}));
