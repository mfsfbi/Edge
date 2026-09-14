# O Mobility — V11 Dashboard Routes

This build makes the provider entry URLs explicit and versioned:

- /O-Ride
- /O-Drive
- /O-drive
- /O-Movers
- /O-Mover
- /o-movers

Unauthenticated providers are sent to the provider login and then returned to the correct service dashboard after successful login.

## Deployment check

After deploying, open:

`/health`

It must return JSON containing:

`"version": "V11-DASHBOARD-ROUTES"`

and the route list containing `/O-Ride`, `/O-Drive`, and `/O-Movers`.

If `/health` still shows an older version, Render is running an older commit/package and the provider-route fix has not been deployed.

## Render

Keep the start command:

`gunicorn --workers 2 --threads 4 --timeout 120 app:app`

Required environment variables are only:

- `USER_NAME`
- `PASSWORD`
