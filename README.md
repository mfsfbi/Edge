# O Mobility

O is a mobile-first PWA for:
- O-Ride — bike passenger service
- O-Drive — car service
- O-Movers — moving service
- O-Travels — links to https://otravel-bleg.onrender.com/

## Render
Only two environment variables are required:

- `USER_NAME`
- `PASSWORD`

Admin entry: `/promise212324`
Provider entries:
- `/O-Rider` — O-Ride partners
- `/O-Drive` — O-Drive partners
- `/O-Movers` — O-Movers partners

Customers use `/` then `/services` and the public service pages. Provider accounts are created by Admin; there is no public provider self-registration.

`render.yaml` includes a persistent disk at `/var/data` for production data retention. On Render, use a compatible persistent-disk service plan when you need data to survive redeploys.

## V10 mobility flow updates
- `/O-Ride` opens the O-Ride rider dashboard entry and then the service-specific login.
- `/O-Drive` and `/O-Movers` behave the same for their service partners.
- Nearest available partner is selected using current reported partner coordinates.
- Partner status visuals: orange = available, green = customer assigned/approaching, blue = passenger onboard; completion returns the partner to available.
- `/api/route` uses OSRM road routing for map lines and road distance, with a straight-line fallback only if routing is temporarily unavailable.
- Admin Control Room has a Simulate switch and a safe full-journey demonstration page.
