# INTEX Pest — deployment note

Deploy the contents of this package normally to Render.

After the new deploy is live, open the public site once in an incognito/private window or hard-refresh it. The service worker is now `intex-v3` and `/sw.js` is served with no-cache headers so the browser is prompted to pick up the new build.

Public site: `/`
Management workspace: `/admin`
Employee workspace: `/employees`
Employee scan surface: `/employees/scan`
Public visitor QR image: `/visitor-qr.png`
Visitor form: `/visit`
