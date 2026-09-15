# O System

O is a Flask + SQLite transport/service platform built on the existing Open Road application foundation. The original trip, ticketing, messaging, visitor analytics, content, QR, backup and administration features remain available under the existing routes; the primary public experience is now the O service layer.

## Render

Procfile:
`web: gunicorn app:app`

Set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in Render environment variables. Set `SECRET/COOKIE` values as appropriate for the deployment. `O_ROUTING_URL` defaults to the public OSRM routing service and can be changed to a compatible routing endpoint.

## O

Public entry: `/o/`

People: `/o/people`

O administration: `/o-control/` (requires the protected admin login)

O supports customer accounts, Rider/Driver/Mover provider accounts, server-side provider-role authorization, provider QR entry, service requests, route distance/time, configurable fare estimation, provider location updates, live request polling, Leaflet/OpenStreetMap presentation, PWA shell and offline-aware static caching.

Provider passwords are hashed. QR codes contain secure provider tokens, not passwords.
