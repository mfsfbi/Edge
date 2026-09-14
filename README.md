# O-System V1

Clean rebuild of O Mobility for customer, partner and admin operations.

## Entry points
- `/` customer home
- `/services` customer service selection
- `/account/register` customer registration
- `/login` universal customer/partner login
- `/partner-login` partner login entry
- `/O-Ride` O-Ride partner login/dashboard entry
- `/O-Drive` O-Drive partner login/dashboard entry
- `/O-Movers` O-Movers partner login/dashboard entry
- `/promise212324` admin login/control room

## Render
Set exactly these secret environment variables:
- `USER_NAME`
- `PASSWORD`

The service includes a 1 GB persistent disk at `/var/data` for SQLite data.
