# O System

A from-scratch O transport/service foundation built for Render. The main product is **O**; `otravel-bleg.onrender.com` is only linked as **O Travel** and is not copied into this project.

## Render
Build: `pip install -r requirements.txt`
Start: `gunicorn app:app` (also included in `Procfile`)

Required Render environment variables:

- `USER_NAME` — O admin login name
- `PASSWORD` — O admin login password

Optional:

- `SECRET_KEY` — persistent Flask session secret. When omitted, O derives a stable secret from the two required admin variables so no third Render variable is required.
- `OSRM_URL` — routing service base URL; defaults to the public OSRM router.
- `O_DB_PATH` — SQLite path; defaults to `data/o.db`.
- `COOKIE_SECURE=1` — enable secure-only session cookies when deployed behind HTTPS.

## Core product

- branded O opening with first-open words and rotating red O identity
- white/red professional visual system
- O-Ride, O-Drive and O-Movers
- public service experience before account creation
- browser geolocation with explicit permission and manual map fallback
- Leaflet/OpenStreetMap map with real road routing through OSRM
- customer accounts and saved request history
- separate Rider / Driver / Mover provider accounts
- server-side provider role enforcement
- admin control using `USER_NAME` / `PASSWORD`
- people/provider management
- request status lifecycle
- complaints before and after registration
- ratings/comments for registered users
- dynamic invite QR using the current site origin, never a hardcoded production hostname
- PWA manifest, service worker and install prompt
- desktop and mobile layouts
- O Travel button only; O Travel is not bundled or duplicated

## Important deployment note

SQLite is included because it keeps the foundation self-contained. On Render, use a persistent disk or move the database to a managed database when durable production data is required.
