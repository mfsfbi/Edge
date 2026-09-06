from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urlparse

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
        CREATE TABLE IF NOT EXISTS production_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_no TEXT NOT NULL,
            product TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT 'Preparation',
            status TEXT NOT NULL DEFAULT 'Open',
            operator TEXT,
            started_at TEXT NOT NULL,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS material_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_no TEXT NOT NULL,
            material_name TEXT NOT NULL,
            quantity TEXT NOT NULL,
            unit TEXT NOT NULL,
            remaining TEXT,
            recorded_by TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS formulations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product TEXT NOT NULL,
            version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Approved',
            controlled_reference TEXT,
            last_reviewed TEXT
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS enquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            subject TEXT NOT NULL,
            message TEXT NOT NULL,
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
    if con.execute("SELECT COUNT(*) FROM formulations").fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO formulations(product,version,status,controlled_reference,last_reviewed) VALUES (?,?,?,?,?)",
            [
                ("Product Alpha", "v1.0", "Approved", "Master Formula / Controlled Copy", date.today().isoformat()),
                ("Product Beta", "v2.1", "Approved", "Master Formula / Controlled Copy", date.today().isoformat()),
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


def external_social(value: str, platform: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("https://") or value.startswith("http://"):
        return value
    value = value.lstrip("@/")
    bases = {
        "facebook": "https://www.facebook.com/",
        "instagram": "https://www.instagram.com/",
        "tiktok": "https://www.tiktok.com/@",
        "linkedin": "https://www.linkedin.com/in/",
        "x": "https://x.com/",
    }
    return bases.get(platform, "") + value if value else ""


@app.context_processor
def inject_globals():
    s = settings()
    socials = {k: external_social(s.get(k, ""), k) for k in ["facebook", "instagram", "tiktok", "linkedin", "x"]}
    con = db()
    summary = con.execute("SELECT COALESCE(AVG(rating),0) average, COUNT(*) count FROM reviews").fetchone()
    reviews = con.execute("SELECT * FROM reviews ORDER BY id DESC LIMIT 6").fetchall()
    con.close()
    average = float(summary["average"] or 0)
    review_summary = {"average": average, "count": int(summary["count"] or 0), "rounded": int(round(average)) if average else 0}
    return {"site": s, "socials": socials, "reviews": reviews, "review_summary": review_summary, "now": datetime.now()}


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/services")
def services():
    return render_template("services.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        payload = request.form
        name = (payload.get("name") or "Guest").strip()
        phone = (payload.get("phone") or "").strip()
        email = (payload.get("email") or "").strip()
        subject = (payload.get("subject") or "General enquiry").strip()
        message = (payload.get("message") or "").strip()
        if name and phone and message:
            con = db()
            con.execute(
                "INSERT INTO enquiries(name,phone,email,subject,message,created_at) VALUES(?,?,?,?,?,?)",
                (name, phone, email, subject, message, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            con.commit(); con.close()
            return render_template("contact.html", sent=True)
    return render_template("contact.html", sent=False)


@app.route("/review", methods=["POST"])
def review():
    name = (request.form.get("name") or "Guest").strip()
    comment = (request.form.get("comment") or "").strip()
    try:
        rating = max(1, min(5, int(request.form.get("rating", "5"))))
    except ValueError:
        rating = 5
    if name and comment:
        con = db()
        con.execute(
            "INSERT INTO reviews(name,rating,comment,created_at) VALUES(?,?,?,?)",
            (name, rating, comment, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        con.commit(); con.close()
    return redirect(url_for("home") + "#reviews")


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
    batches = con.execute("SELECT * FROM production_batches ORDER BY id DESC LIMIT 8").fetchall()
    usage = con.execute("SELECT * FROM material_usage ORDER BY id DESC LIMIT 10").fetchall()
    enquiries = con.execute("SELECT * FROM enquiries ORDER BY id DESC LIMIT 8").fetchall()
    reviews_admin = con.execute("SELECT * FROM reviews ORDER BY id DESC LIMIT 8").fetchall()
    review_summary = con.execute("SELECT COALESCE(AVG(rating),0) average, COUNT(*) count FROM reviews").fetchone()
    totals = con.execute(
        "SELECT COALESCE(SUM(CASE WHEN kind='income' THEN amount ELSE 0 END),0) income, "
        "COALESCE(SUM(CASE WHEN kind='expense' THEN amount ELSE 0 END),0) expense FROM transactions"
    ).fetchone()
    visitor_count = con.execute("SELECT COUNT(*) c FROM visitors").fetchone()["c"]
    active_batches = con.execute("SELECT COUNT(*) c FROM production_batches WHERE status IN ('Open','In progress')").fetchone()["c"]
    con.close()
    profit = totals["income"] - totals["expense"]
    return render_template("admin.html", visitors=visitors, transactions=transactions, employees=employees,
                           batches=batches, usage=usage, enquiries=enquiries, reviews_admin=reviews_admin,
                           review_average=float(review_summary["average"] or 0), review_count=int(review_summary["count"] or 0),
                           income=totals["income"], expense=totals["expense"], profit=profit,
                           visitor_count=visitor_count, active_batches=active_batches)


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
    formulations = con.execute("SELECT * FROM formulations ORDER BY product").fetchall()
    batches = con.execute("SELECT * FROM production_batches ORDER BY id DESC LIMIT 12").fetchall()
    usage = con.execute("SELECT * FROM material_usage ORDER BY id DESC LIMIT 14").fetchall()
    con.close()
    descriptions = {
        "Operations": "Coordinates work allocation, scheduling and site follow-through.",
        "Customer Care": "Handles client communication, enquiries and follow-up.",
        "Pharmaceutical Operations": "Works from controlled technical documents, records production activity and escalates quality or safety issues.",
    }
    roles = []
    seen = set()
    for e in team:
        role = e["role"] or "Team"
        if role not in seen:
            roles.append({"role": role, "description": descriptions.get(role, "Complete assigned duties and record work clearly.")})
            seen.add(role)
    return render_template("employees.html", team=team, tasks=tasks, formulations=formulations, batches=batches, usage=usage, responsibilities=roles)


@app.route("/employee/batch", methods=["POST"])
def add_batch():
    con = db()
    con.execute("INSERT INTO production_batches(batch_no,product,stage,status,operator,started_at,notes) VALUES(?,?,?,?,?,?,?)", (
        request.form.get("batch_no", "BATCH-NEW"), request.form.get("product", "Unspecified product"),
        request.form.get("stage", "Preparation"), request.form.get("status", "Open"),
        request.form.get("operator", "Team"), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), request.form.get("notes", "")
    ))
    con.commit(); con.close()
    return redirect(url_for("employees") + "#production")


@app.route("/employee/material", methods=["POST"])
def add_material_usage():
    con = db()
    con.execute("INSERT INTO material_usage(batch_no,material_name,quantity,unit,remaining,recorded_by,created_at) VALUES(?,?,?,?,?,?,?)", (
        request.form.get("batch_no", ""), request.form.get("material_name", ""), request.form.get("quantity", ""),
        request.form.get("unit", ""), request.form.get("remaining", ""), request.form.get("recorded_by", ""),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    con.commit(); con.close()
    return redirect(url_for("employees") + "#materials")


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
