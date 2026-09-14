# O-System V1 — Complete Customer UI Build

This build keeps the full customer, partner, admin, feedback, QR, PWA and dispatch surfaces and adds a redesigned customer trip interface.

## Customer experience
- Bright customer UI with service picker and live map together.
- Pickup is taken from browser geolocation automatically; editing pickup is optional.
- Destination search suggests nearby/recognized places while typing, with map selection as an alternative.
- Road geometry comes from OSRM rather than straight-line drawings.
- Available partners appear on the map only after a service is selected.
- Tapping a partner marker opens rating average, completed-trip count, vehicle details and recent written reviews.
- After assignment the customer's map focuses on the assigned partner; the pickup route is shown while approaching and the destination route is shown after trip start.
- Customer app ratings and per-partner trip ratings use real 1–5 star controls; partner averages are calculated from submitted trip ratings.
- Guest users can request services and submit help/complaints; registered customers get trips, ratings, account and appearance features.

## Partner/Admin
- O-Ride, O-Drive and O-Movers partner entry and dashboards remain available.
- Partner statuses: orange available, green assigned/approaching, blue on trip.
- Nearest available partner matching remains atomic.
- Admin Control Room retains service views, live map, inbox, complaints, ratings, partners, people/devices, simulation and system errors.
- Admin access path remains `/promise212324` using Render `USER_NAME` and `PASSWORD`.

## Deployment
Set the existing Render `USER_NAME` and `PASSWORD` environment variables. The QR target is generated from the current deployment origin. No Intex hostname is hard-coded.
