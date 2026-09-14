# O Mobility

Mobile-first Flask PWA for O-Ride (boda), O-Drive (cars), O-Movers, and O-Travels. O-Travels links to the existing OTravel site.

## Render variables
Only these two are required:

- `USER_NAME`
- `PASSWORD`

The secret admin entry is `/promise212324`.

Use a persistent disk mounted at `/var/data` for production data retention.

## Public experience
Visitors can browse anonymously. Pickup can use device location or a searched place; destinations can be searched or selected on the map. The fare estimate appears before requesting.

## PWA
The app includes root service-worker scope, installable PNG icons, an install prompt when the browser supports it, and a clear fallback instruction for iOS/unsupported browsers.

## Admin
The control room handles partner verification/deactivation, fares, requests, live partner locations, visitor context, complaints, ratings, audits, and backups. Operational records are retained rather than hard-deleted.
