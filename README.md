# O-System V1 — Restored Operations Build

This build restores the complete customer, partner and admin product surface and keeps the newer dispatch behavior.

## Public/customer
- Guest access to core services
- Optional customer account, trips, ratings, appearance and account settings
- Guest/customer help, concern, complaint or request
- Always-visible deployment-aware O QR
- Bright service/customer interface

## Partners
- `/O-Ride`, `/O-Drive`, `/O-Movers`
- Admin-created partner accounts
- Orange available / green assigned / blue onboard status
- Location-aware matching
- Partner requests, earnings, ratings and help
- Road-routing where available

## Admin
Access only at `/promise212324` using `USER_NAME` and `PASSWORD` Render environment variables.

Admin includes:
- O-Ride service control
- O-Drive service control
- O-Movers service control
- Live all-network map
- People & devices
- Inbox
- Complaints
- Partners
- Simulation
- System errors
- Service request/customer views

## Storage
Uses `/var/data/o_system_v1.db` when writable, otherwise local `instance/`. Render persistent disk is included in `render.yaml`.
