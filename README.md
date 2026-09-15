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
