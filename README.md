# O Mobility PWA

Standalone Flask PWA for O-Bikes, O-Ride and O-Movers, with O-Travel linking to the existing OTravel adventure platform.

## Render deployment

This package includes a `render.yaml` that attaches a 1 GB persistent disk at `/var/data`. Render documents that persistent disks preserve filesystem changes under their mount path and require a paid compatible service; the default filesystem is otherwise ephemeral. citeturn839913search0turn839913search3

If deploying manually instead of using the blueprint, attach a persistent disk mounted at `/var/data` and set `DATA_DIR=/var/data`.

## Required Render variables

- `USER_NAME` — your private control-room username.
- `PASSWORD` — your private control-room password.
- `SECRET_KEY` — generate a strong secret; the included Blueprint can generate it.

Optional:
- `OTRAVEL_URL` — defaults to `https://otravel-bleg.onrender.com/`.

## Admin

The public control-room entry is intentionally hidden at `/promise212324`. `/admin` is blocked. Enter the `USER_NAME` and `PASSWORD` Render values there. Admin can verify/deactivate/reactivate riders and customers, manage fares and commission, resolve complaints, inspect live partner positions, inspect anonymized/identified visitor device and consented location data, and download SQLite/JSON backups. Records are soft-deactivated rather than hard-deleted.

## Privacy / device details

The browser cannot guarantee an exact physical handset model on every platform. Where supported, O reads User-Agent Client Hints such as model/platform; otherwise it records a normalized device family and browser family instead of pretending the browser brand is the phone. Location is only stored when the browser permission flow provides coordinates. Anonymous visitors can browse without an account.

## Guest ordering

Customers can browse anonymously. A guest request gets an internal anonymous user record; the optional contact phone can be supplied at checkout. Creating an O account is separate and remains optional.

## Fare model

Default prices are deliberately simple and can be edited from Admin. The intent is to give customers a clear upfront estimate and keep O competitive, but live market prices should be reviewed before public launch rather than promising that O is always cheaper than a competitor.
