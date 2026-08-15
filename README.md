# Toror Technologies Hospital Management System (TTHMS)

A direct-link prototype of a hospital management platform. Authentication is intentionally disabled in this version so the ICT team can access modules through routes/links while the workflow is being developed.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Open `http://127.0.0.1:5000/dashboard`.

## Included prototype modules
Dashboard, Reception, Appointments, Patients + medical timeline, Consultations, Laboratory, Pharmacy, Admissions, Billing, Inventory, Reports, AI Assistant scaffold, Backups, Administration.

## Data
SQLite database is created automatically in `instance/tthms.db` and seeded with demo records. Back up the `instance/` directory during development. Production should add encrypted backup/export, proper authentication/authorization, audit controls, and clinical safety validation before patient use.
