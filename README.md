# Toror Technologies Hospital Management System (TTHMS)

A direct-link prototype of a hospital management platform. Authentication is intentionally disabled in this version so the ICT team can access modules through routes/links while the workflow is being developed.

## Database: MongoDB

This build uses **MongoDB** instead of SQLite. The app still runs with the familiar command:

```bash
pip install -r requirements.txt
python app.py
```

### Local MongoDB

The default connection is:

```text
mongodb://127.0.0.1:27017
```

Start MongoDB locally, then run `python app.py`.

### MongoDB Atlas / hosted MongoDB

Set `MONGO_URI` before starting the app. Optionally set `MONGO_DB` (default: `tthms`).

Windows PowerShell:

```powershell
$env:MONGO_URI="mongodb+srv://USER:PASSWORD@CLUSTER.mongodb.net/?retryWrites=true&w=majority"
python app.py
```

Linux/macOS:

```bash
export MONGO_URI="mongodb+srv://USER:PASSWORD@CLUSTER.mongodb.net/?retryWrites=true&w=majority"
python app.py
```

The application creates its MongoDB collections and indexes automatically and seeds demo patients/inventory on an empty database.

Open `http://127.0.0.1:5000/dashboard`.

## Health check

`/health` confirms whether the application can reach MongoDB.

## Included prototype modules

Dashboard, Reception, Appointments, Patients + medical timeline, Consultations, Laboratory, Pharmacy, Admissions, Billing, Inventory, Reports, AI Assistant scaffold, Backups, Administration.

## Deployment

The included Procfile uses Gunicorn. Set `MONGO_URI` in the hosting provider's environment variables. For production, add authentication/authorization, encrypted/verified backups, audit controls, clinical safety validation, secrets management, and HTTPS.

## MongoDB backups

Use `mongodump` for self-hosted MongoDB or MongoDB Atlas backup/snapshot features for hosted MongoDB. The `/backups` screen explains this rather than pretending a SQLite file exists.
