from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, date
from pathlib import Path

import qrcode
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "intex.db"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "intex-demo-secret")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "svg"}


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT,
            purpose TEXT,
            location TEXT,
            qr_token TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Active',
            phone TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            owner TEXT,
            status TEXT NOT NULL DEFAULT 'Open',
            due_date TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    defaults = {
        "company_name": "INTEX",
        "tagline": "Pharmaceuticals, formulation and quality — clearly delivered.",
        "phone": "0702717779",
        "whatsapp": "254702717779",
        "email": "hello@intex.co.ke",
        "domain": "https://www.intex.co.ke",
        "address": "Nairobi, Kenya",
        "logo": "logo.svg",
        "primary_color": "#741b3d",
        "facebook": "",
        "instagram": "",
        "tiktok": "",
        "linkedin": "",
        "x": "",
        "rating": "",
        "years_experience": "",
        "clients_served": "",
        "map_lat": "-1.2921",
        "map_lng": "36.8219",
        "map_label": "INTEX — Nairobi, Kenya",
    }
    for key, value in defaults.items():
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (key, value))
    if con.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO employees(name,role,status,phone,created_at) VALUES (?,?,?,?,?)",
            [
                ("Field Team Lead", "Operations", "Active", "0700000000", datetime.utcnow().isoformat()),
                ("Client Service Desk", "Customer Care", "Active", "0711111111", datetime.utcnow().isoformat()),
                ("Technical Officer", "Pharmaceutical Operations", "Active", "0722222222", datetime.utcnow().isoformat()),
            ],
        )
    con.commit()
    con.close()


def settings():
    con = db()
    rows = con.execute("SELECT key,value FROM settings").fetchall()
    con.close()
    return {r["key"]: r["value"] for r in rows}


def set_setting(key, value):
    con = db()
    con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    con.commit()
    con.close()


def money(v):
    return f"KES {v:,.0f}"


@app.context_processor
def inject_globals():
    s = settings()
    return {"site": s, "now": datetime.now()}


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/services")
def services():
    return render_template("services.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/visit", methods=["GET", "POST"])
def visit():
    if request.method == "POST":
        payload = request.get_json(silent=True) or request.form
        name = (payload.get("name") or "Guest").strip()
        phone = (payload.get("phone") or "").strip()
        purpose = (payload.get("purpose") or "General enquiry").strip()
        location = (payload.get("location") or "Not shared").strip()
        token = uuid.uuid4().hex[:10]
        con = db()
        con.execute(
            "INSERT INTO visitors(name,phone,purpose,location,qr_token,created_at) VALUES(?,?,?,?,?,?)",
            (name, phone, purpose, location, token, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        con.commit()
        con.close()
        if request.is_json:
            return jsonify({"ok": True, "token": token})
        return render_template("visit.html", success=True, token=token)
    return render_template("visit.html", success=False, token=None)


@app.route("/pulse_receiver", methods=["GET", "POST", "HEAD", "OPTIONS"])
def pulse_receiver():
    """Lightweight keep-alive endpoint for the Breathe heartbeat service.

    Accepts the heartbeat methods without touching application data and always
    returns HTTP 200 so an external uptime/keep-alive service can confirm the
    service is awake.
    """
    return jsonify({
        "ok": True,
        "service": "intex-pharma",
        "pulse": "received",
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }), 200


@app.route("/api/chat", methods=["POST"])
def chat():
    q = ((request.get_json(silent=True) or {}).get("message") or "").lower().strip()
    s = settings()
    if any(x in q for x in ["price", "cost", "quote", "how much"]):
        a = f"We can prepare a tailored estimate. Call {s['phone']} or WhatsApp us for a technical enquiry."
    elif any(x in q for x in ["formulation", "mixing", "batch"]):
        a = "Our workflow is organized around approved formulation references, controlled batch preparation, mixing records, sampling and quality review. Specific recipes and process parameters should come from authorized technical documentation."
    elif any(x in q for x in ["laboratory", "lab", "testing", "analysis"]):
        a = "Laboratory work can be organized around sample registration, test records, analysis, result capture and review linked to the relevant product or batch."
    elif any(x in q for x in ["quality", "qc", "compliance"]):
        a = "Quality operations can cover document control, checks, holds, deviations, approvals, traceability and final release decisions."
    elif any(x in q for x in ["product", "products", "medicine", "pharmaceutical"]):
        a = "The product catalogue can be organized by product family, formulation or dosage form, specifications, packaging and release status."
    elif any(x in q for x in ["location", "where", "nairobi"]):
        a = f"Current office location: {s['address']}."
    elif any(x in q for x in ["hours", "open", "working"]):
        a = "Our customer desk can route enquiries during business hours; urgent technical enquiries can start through WhatsApp."
    elif any(x in q for x in ["contact", "phone", "email", "quote", "enquiry"]):
        a = f"You can contact {s['company_name']} at {s['phone']} or {s['email']}."
    else:
        a = f"I can help with pharmaceutical formulation, laboratory work, production, quality, products and contact details. You can also call {s['phone']}."
    return jsonify({"reply": a})

@app.route("/api/site")
def api_site():
    return jsonify(settings())


@app.route("/visitor-qr.png")
def visitor_qr():
    """Generate the public visitor QR from the current host so deployments never use a stale code."""
    from io import BytesIO
    qr_url = url_for("visit", _external=True)
    img = qrcode.make(qr_url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    from flask import send_file
    response = send_file(buf, mimetype="image/png", download_name="intex-visitor-qr.png")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.route("/admin")
def admin():
    con = db()
    visitors = con.execute("SELECT * FROM visitors ORDER BY id DESC LIMIT 8").fetchall()
    transactions = con.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT 8").fetchall()
    employees = con.execute("SELECT * FROM employees ORDER BY id DESC").fetchall()
    totals = con.execute(
        "SELECT COALESCE(SUM(CASE WHEN kind='income' THEN amount ELSE 0 END),0) income, "
        "COALESCE(SUM(CASE WHEN kind='expense' THEN amount ELSE 0 END),0) expense FROM transactions"
    ).fetchone()
    visitor_count = con.execute("SELECT COUNT(*) c FROM visitors").fetchone()["c"]
    con.close()
    profit = totals["income"] - totals["expense"]
    return render_template("admin.html", visitors=visitors, transactions=transactions, employees=employees,
                           income=totals["income"], expense=totals["expense"], profit=profit,
                           visitor_count=visitor_count)


@app.route("/admin/transaction", methods=["POST"])
def add_transaction():
    con = db()
    amount = float(request.form.get("amount") or 0)
    con.execute("INSERT INTO transactions(kind,category,amount,note,created_at) VALUES(?,?,?,?,?)", (
        request.form.get("kind", "income"), request.form.get("category", "General"), amount,
        request.form.get("note", ""), datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    con.commit(); con.close()
    return redirect(url_for("admin") + "#finance")


@app.route("/admin/employee", methods=["POST"])
def add_employee():
    con = db()
    con.execute("INSERT INTO employees(name,role,status,phone,created_at) VALUES(?,?,?,?,?)", (
        request.form.get("name", "New Employee"), request.form.get("role", "Team"),
        request.form.get("status", "Active"), request.form.get("phone", ""),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    con.commit(); con.close()
    return redirect(url_for("admin") + "#people")


@app.route("/admin/settings", methods=["POST"])
def update_settings():
    for key in ["company_name", "tagline", "phone", "whatsapp", "email", "domain", "address", "facebook", "instagram", "tiktok", "linkedin", "x", "rating", "years_experience", "clients_served", "map_lat", "map_lng", "map_label"]:
        if key in request.form:
            set_setting(key, request.form[key].strip())
    file = request.files.get("logo")
    if file and file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext in ALLOWED_EXTENSIONS:
            filename = secure_filename(f"brand-logo.{ext}")
            file.save(UPLOAD_DIR / filename)
            set_setting("logo", filename)
    return redirect(url_for("admin") + "#settings")


@app.route("/admin/backup")
def backup_db():
    from flask import send_file
    return send_file(DB_PATH, as_attachment=True, download_name=f"intex-backup-{date.today().isoformat()}.db")


@app.route("/employees")
def employees():
    con = db()
    team = con.execute("SELECT * FROM employees ORDER BY name").fetchall()
    tasks = con.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 12").fetchall()
    con.close()
    descriptions = {
        "Operations": "Coordinates field work, scheduling and site follow-through.",
        "Customer Care": "Handles client communication, enquiries and follow-up.",
        "Pharmaceutical Operations": "Supports formulation, production, laboratory coordination and controlled operational records.",
    }
    roles = []
    seen = set()
    for e in team:
        role = e["role"] or "Team"
        if role not in seen:
            roles.append({"role": role, "description": descriptions.get(role, "Complete assigned field duties and report work clearly.")})
            seen.add(role)
    return render_template("employees.html", team=team, tasks=tasks, responsibilities=roles)


@app.route("/employees/scan")
def employee_scan():
    return render_template("employee_scan.html")


@app.route("/employee/task", methods=["POST"])
def add_task():
    con = db()
    con.execute("INSERT INTO tasks(title,owner,status,due_date,created_at) VALUES(?,?,?,?,?)", (
        request.form.get("title", "Follow up client"), request.form.get("owner", "Team"),
        request.form.get("status", "Open"), request.form.get("due_date", ""),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    con.commit(); con.close()
    return redirect(url_for("employees"))


@app.route("/logo/<path:filename>")
def logo_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/manifest.webmanifest")
def manifest():
    return jsonify({
        "name": settings()["company_name"],
        "short_name": "INTEX",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f7faf8",
        "theme_color": settings().get("primary_color", "#0b6b57"),
        "icons": [{"src": "/static/uploads/" + settings().get("logo", "logo.svg"), "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}],
    })


@app.route("/robots.txt")
def robots():
    return "User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /employees\nSitemap: /sitemap.xml\n", 200, {"Content-Type": "text/plain"}


@app.route("/sitemap.xml")
def sitemap():
    base = request.url_root.rstrip("/")
    urls = ["/", "/services", "/contact", "/visit"]
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml.append(f"<url><loc>{base}{u}</loc></url>")
    xml.append("</urlset>")
    return "\n".join(xml), 200, {"Content-Type": "application/xml"}


@app.route("/sw.js")
def sw():
    response = send_from_directory(BASE_DIR / "static", "sw.js", mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


init_db()

if __name__ == "__main__":
    app.run(debug=True)
