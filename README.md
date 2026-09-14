# O Mobility PWA

O-Bikes, O-Ride and O-Movers, with O-Travel linking to the existing OTravel site.

## Render
Set exactly two environment variables:

- `USER_NAME` — private control-room username
- `PASSWORD` — private control-room password

Admin is deliberately hidden at `/promise212324`. Normal users never need that path.

Use the included Render Blueprint or attach a persistent disk mounted at `/var/data`. The application automatically falls back to `instance/` when `/var/data` is unavailable, which prevents the PermissionError that occurs on services without a writable `/var/data`.

## Start
`gunicorn --workers 2 --threads 4 --timeout 120 app:app`

## PWA
The service worker is exposed at `/sw.js` so it can control the whole site scope.

## Data
Operational users and trips are never hard-deleted by admin actions. Admin can deactivate users while retaining their history. Backups and JSON exports are available from the control room.
