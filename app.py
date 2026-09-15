import os, secrets, sqlite3, hashlib
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv('O_DB_PATH', os.path.join(BASE_DIR, 'data', 'o.db'))
ADMIN_USER = os.getenv('USER_NAME', 'admin')
ADMIN_PASSWORD = os.getenv('PASSWORD', 'change-me')
OSRM_URL = os.getenv('OSRM_URL', 'https://router.project-osrm.org')
APP_NAME = 'O'
TRAVEL_URL = 'https://otravel-bleg.onrender.com'

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or hashlib.sha256(f'{ADMIN_USER}|{ADMIN_PASSWORD}|O-SYSTEM'.encode()).hexdigest()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE','0')=='1')

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db

@app.teardown_appcontext
def close_db(exc=None):
    conn = g.pop('db', None)
    if conn:
        conn.close()

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript('''
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      identifier TEXT UNIQUE NOT NULL,
      phone TEXT,
      password_hash TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      last_seen_at TEXT
    );
    CREATE TABLE IF NOT EXISTS providers (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      identifier TEXT UNIQUE NOT NULL,
      phone TEXT,
      ref_code TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('Rider','Driver','Mover')),
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      last_seen_at TEXT
    );
    CREATE TABLE IF NOT EXISTS requests (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,
      service TEXT NOT NULL,
      pickup_lat REAL NOT NULL,
      pickup_lng REAL NOT NULL,
      destination_lat REAL NOT NULL,
      destination_lng REAL NOT NULL,
      pickup_label TEXT,
      destination_label TEXT,
      payment_method TEXT,
      fare REAL,
      distance_km REAL,
      duration_min REAL,
      status TEXT NOT NULL DEFAULT 'New',
      provider_id INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id),
      FOREIGN KEY(provider_id) REFERENCES providers(id)
    );
    CREATE TABLE IF NOT EXISTS ratings (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
      comment TEXT,
      created_at TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS complaints (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,
      name TEXT,
      contact TEXT,
      message TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'Open',
      created_at TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS invite_tokens (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      token TEXT UNIQUE NOT NULL,
      created_at TEXT NOT NULL,
      expires_at TEXT
    );
    CREATE TABLE IF NOT EXISTS audit_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      actor_type TEXT,
      actor_id INTEGER,
      action TEXT NOT NULL,
      details TEXT,
      created_at TEXT NOT NULL
    );
    ''')
    con.commit(); con.close()

init_db()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def audit(actor_type, actor_id, action, details=''):
    db().execute('INSERT INTO audit_log(actor_type,actor_id,action,details,created_at) VALUES (?,?,?,?,?)', (actor_type,actor_id,action,details,now_iso()))
    db().commit()

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('admin'):
            return jsonify(error='Admin authentication required'), 401
        return fn(*args, **kwargs)
    return wrapper

def user_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify(error='Account required'), 401
        return fn(*args, **kwargs)
    return wrapper

def provider_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('provider_id'):
            return jsonify(error='Provider authentication required'), 401
        return fn(*args, **kwargs)
    return wrapper

@app.get('/api/health')
def health():
    return jsonify(ok=True, service='O', time=now_iso())

@app.route('/')
def index():
    return render_template('index.html', travel_url=TRAVEL_URL, app_name=APP_NAME, canonical=request.url_root.rstrip('/'))

@app.route('/app')
def app_shell():
    return render_template('app.html', travel_url=TRAVEL_URL, app_name=APP_NAME, canonical=request.url_root.rstrip('/') + '/app', noindex=True)

@app.route('/login')
def login_page():
    return render_template('auth.html', mode='login', app_name=APP_NAME, noindex=True)

@app.route('/register')
def register_page():
    return render_template('auth.html', mode='register', app_name=APP_NAME, noindex=True)

@app.route('/people')
def people_page():
    return render_template('people.html', app_name=APP_NAME, noindex=True)

@app.route('/admin')
def admin_page():
    return render_template('admin.html', app_name=APP_NAME, noindex=True)

@app.route('/provider/<role_slug>')
def provider_page(role_slug):
    role = {'rider':'Rider','driver':'Driver','mover':'Mover'}.get(role_slug.lower())
    if not role:
        return render_template('error.html', code=404, message='That O role does not exist.'), 404
    return render_template('provider.html', role=role, app_name=APP_NAME, noindex=True)

@app.route('/sw.js')
def service_worker():
    response = app.send_static_file('sw.js')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Service-Worker-Allowed'] = '/'
    response.mimetype = 'application/javascript'
    return response

@app.get('/manifest.json')
def manifest_json():
    return app.send_static_file('manifest.json')

@app.get('/robots.txt')
def robots_txt():
    base = request.url_root.rstrip('/')
    body = "User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /login\nDisallow: /register\nDisallow: /people\nDisallow: /provider/\nDisallow: /api/\nSitemap: " + base + "/sitemap.xml\n"
    return app.response_class(body, mimetype='text/plain')

@app.get('/sitemap.xml')
def sitemap_xml():
    base = request.url_root.rstrip('/')
    urls = ['/', '/o-ride', '/o-drive', '/o-movers']
    items = ''.join('<url><loc>' + base + u + '</loc></url>' for u in urls)
    xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + items + '</urlset>'
    return app.response_class(xml, mimetype='application/xml')

@app.get('/o-ride')
def o_ride_page():
    return render_template('service_page.html', service='O-Ride', heading='O-Ride in Kenya', description='O-Ride is O ride booking for convenient city and local transport, with map-based pickup and destination selection.', canonical=request.url_root.rstrip('/') + '/o-ride')

@app.get('/o-drive')
def o_drive_page():
    return render_template('service_page.html', service='O-Drive', heading='O-Drive in Kenya', description='O-Drive connects customers with O driving and transport services using a real map and location-aware service flow.', canonical=request.url_root.rstrip('/') + '/o-drive')

@app.get('/o-movers')
def o_movers_page():
    return render_template('service_page.html', service='O-Movers', heading='O-Movers in Kenya', description='O-Movers helps customers request moving and delivery services with location-aware pickup, destination and route information.', canonical=request.url_root.rstrip('/') + '/o-movers')

@app.post('/api/auth/register')
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    identifier = (data.get('identifier') or '').strip().lower()
    phone = (data.get('phone') or '').strip()
    password = data.get('password') or ''
    if len(name) < 2 or len(identifier) < 3 or len(password) < 6:
        return jsonify(error='Name, login identifier and a 6+ character password are required.'), 400
    try:
        cur = db().execute('INSERT INTO users(name,identifier,phone,password_hash,created_at) VALUES (?,?,?,?,?)', (name,identifier,phone,generate_password_hash(password),now_iso()))
        db().commit()
    except sqlite3.IntegrityError:
        return jsonify(error='That identifier is already in O.'), 409
    session.clear(); session['user_id'] = cur.lastrowid
    audit('user', cur.lastrowid, 'register')
    return jsonify(ok=True, redirect='/app')

@app.post('/api/auth/login')
def login():
    data = request.get_json(silent=True) or {}
    identifier = (data.get('identifier') or '').strip().lower()
    password = data.get('password') or ''
    row = db().execute('SELECT * FROM users WHERE identifier=? AND active=1', (identifier,)).fetchone()
    if not row or not check_password_hash(row['password_hash'], password):
        return jsonify(error='Invalid O account credentials.'), 401
    session.clear(); session['user_id'] = row['id']
    db().execute('UPDATE users SET last_seen_at=? WHERE id=?',(now_iso(),row['id'])); db().commit()
    audit('user', row['id'], 'login')
    return jsonify(ok=True, redirect='/app')

@app.post('/api/auth/logout')
def logout():
    session.clear(); return jsonify(ok=True)

@app.get('/api/me')
def me():
    if session.get('admin'):
        return jsonify(type='admin', user={'identifier': ADMIN_USER})
    if session.get('provider_id'):
        p = db().execute('SELECT id,name,identifier,phone,role,active,ref_code FROM providers WHERE id=?',(session['provider_id'],)).fetchone()
        return jsonify(type='provider', user=dict(p) if p else None)
    if session.get('user_id'):
        u = db().execute('SELECT id,name,identifier,phone,active FROM users WHERE id=?',(session['user_id'],)).fetchone()
        return jsonify(type='user', user=dict(u) if u else None)
    return jsonify(type='guest')

@app.post('/api/people/login')
def provider_login():
    data = request.get_json(silent=True) or {}
    role = data.get('role')
    identifier = (data.get('identifier') or '').strip().lower()
    password = data.get('password') or ''
    if role not in ('Rider','Driver','Mover'):
        return jsonify(error='Choose a valid O role.'), 400
    p = db().execute('SELECT * FROM providers WHERE identifier=? AND role=? AND active=1',(identifier,role)).fetchone()
    if not p or not check_password_hash(p['password_hash'], password):
        return jsonify(error='Invalid provider credentials for that role.'), 401
    session.clear(); session['provider_id'] = p['id']; session['provider_role'] = role
    db().execute('UPDATE providers SET last_seen_at=? WHERE id=?',(now_iso(),p['id'])); db().commit()
    audit('provider',p['id'],'login',role)
    return jsonify(ok=True, redirect=f"/provider/{role.lower()}")

@app.post('/api/complaints')
def complaint():
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    if len(message) < 3: return jsonify(error='Please describe the complaint.'), 400
    uid = session.get('user_id')
    name = (data.get('name') or '').strip()
    contact = (data.get('contact') or '').strip()
    if uid:
        u=db().execute('SELECT name,phone,identifier FROM users WHERE id=?',(uid,)).fetchone()
        name=name or (u['name'] if u else '')
        contact=contact or ((u['phone'] or u['identifier']) if u else '')
    db().execute('INSERT INTO complaints(user_id,name,contact,message,created_at) VALUES(?,?,?,?,?)',(uid,name,contact,message,now_iso()))
    db().commit(); audit('user',uid,'complaint',message[:160])
    return jsonify(ok=True,message='Complaint received.')

@app.post('/api/ratings')
@user_required
def rating():
    data=request.get_json(silent=True) or {}
    try: value=int(data.get('rating'))
    except (TypeError,ValueError): value=0
    if value not in range(1,6): return jsonify(error='Rating must be 1–5.'),400
    comment=(data.get('comment') or '').strip()[:1000]
    uid=session['user_id']
    db().execute('INSERT INTO ratings(user_id,rating,comment,created_at) VALUES(?,?,?,?)',(uid,value,comment,now_iso())); db().commit()
    return jsonify(ok=True)

@app.get('/api/invite')
def invite():
    token=secrets.token_urlsafe(18)
    db().execute('INSERT INTO invite_tokens(token,created_at) VALUES(?,?)',(token,now_iso())); db().commit()
    # No hardcoded host: frontend uses window.location.origin + token.
    return jsonify(token=token)

@app.post('/api/route')
def route_api():
    data=request.get_json(silent=True) or {}
    try:
        a=(float(data['from']['lng']),float(data['from']['lat'])); b=(float(data['to']['lng']),float(data['to']['lat']))
    except Exception:
        return jsonify(error='Valid coordinates required.'),400
    # The browser can call this with the public OSRM service; server proxy avoids CORS issues if configured.
    import urllib.request, json
    coords=f'{a[0]},{a[1]};{b[0]},{b[1]}'
    url=f'{OSRM_URL.rstrip("/")}/route/v1/driving/{coords}?overview=full&geometries=geojson'
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            payload=json.loads(r.read().decode('utf-8'))
        return jsonify(payload)
    except Exception as e:
        return jsonify(error='Routing service unavailable.', detail=str(e)[:120]),502

@app.post('/api/requests')
def create_request():
    data=request.get_json(silent=True) or {}
    service=data.get('service')
    payment=data.get('payment_method') or 'Cash'
    if service not in ('O-Ride','O-Drive','O-Movers'):
        return jsonify(error='Choose a valid O service.'),400
    try:
        pl=data['pickup']; de=data['destination']
        plat,plng=float(pl['lat']),float(pl['lng']); dlat,dlng=float(de['lat']),float(de['lng'])
    except Exception: return jsonify(error='Pickup and destination coordinates are required.'),400
    fare=data.get('fare'); dist=data.get('distance_km'); dur=data.get('duration_min')
    stamp=now_iso()
    cur=db().execute('''INSERT INTO requests(user_id,service,pickup_lat,pickup_lng,destination_lat,destination_lng,pickup_label,destination_label,payment_method,fare,distance_km,duration_min,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (session['user_id'],service,plat,plng,dlat,dlng,data.get('pickup_label','Current location'),data.get('destination_label','Selected destination'),payment,fare,dist,dur,'New',stamp,stamp))
    db().commit(); audit('user',session.get('user_id'),'request',service)
    return jsonify(ok=True, request_id=cur.lastrowid, status='New')

@app.get('/api/my-requests')
@user_required
def my_requests():
    rows=db().execute('SELECT r.*, p.name provider_name, p.role provider_role FROM requests r LEFT JOIN providers p ON p.id=r.provider_id WHERE r.user_id=? ORDER BY r.id DESC LIMIT 30',(session['user_id'],)).fetchall()
    return jsonify(items=[dict(r) for r in rows])

@app.post('/api/admin/login')
def admin_login():
    data=request.get_json(silent=True) or {}
    if secrets.compare_digest(str(data.get('username','')), str(ADMIN_USER)) and secrets.compare_digest(str(data.get('password','')), str(ADMIN_PASSWORD)):
        session.clear(); session['admin']=True; audit('admin',None,'login')
        return jsonify(ok=True,redirect='/admin')
    return jsonify(error='Invalid admin credentials.'),401

@app.post('/api/admin/logout')
def admin_logout():
    session.clear(); return jsonify(ok=True)

@app.get('/api/admin/overview')
@admin_required
def admin_overview():
    c=db()
    return jsonify(stats={
        'users':c.execute('SELECT COUNT(*) n FROM users').fetchone()['n'],
        'providers':c.execute('SELECT COUNT(*) n FROM providers WHERE active=1').fetchone()['n'],
        'requests':c.execute('SELECT COUNT(*) n FROM requests').fetchone()['n'],
        'active_requests':c.execute("SELECT COUNT(*) n FROM requests WHERE status NOT IN ('Completed','Cancelled')").fetchone()['n'],
        'complaints':c.execute("SELECT COUNT(*) n FROM complaints WHERE status='Open'").fetchone()['n'],
        'ratings':c.execute('SELECT COUNT(*) n FROM ratings').fetchone()['n']})

@app.get('/api/admin/providers')
@admin_required
def admin_providers():
    rows=db().execute('SELECT id,name,identifier,phone,ref_code,role,active,created_at,last_seen_at FROM providers ORDER BY role,name').fetchall()
    return jsonify(items=[dict(r) for r in rows])

@app.post('/api/admin/providers')
@admin_required
def admin_create_provider():
    data=request.get_json(silent=True) or {}
    name=(data.get('name') or '').strip(); identifier=(data.get('identifier') or '').strip().lower(); phone=(data.get('phone') or '').strip(); password=data.get('password') or ''; role=data.get('role')
    if len(name)<2 or len(identifier)<3 or len(password)<6 or role not in ('Rider','Driver','Mover'):
        return jsonify(error='Name, identifier, role and 6+ character password are required.'),400
    ref='O-'+secrets.token_hex(5).upper()
    try:
        cur=db().execute('INSERT INTO providers(name,identifier,phone,ref_code,password_hash,role,created_at) VALUES(?,?,?,?,?,?,?)',(name,identifier,phone,ref,generate_password_hash(password),role,now_iso())); db().commit()
    except sqlite3.IntegrityError: return jsonify(error='That provider identifier is already used.'),409
    audit('admin',None,'create_provider',f'{role}:{identifier}')
    return jsonify(ok=True,id=cur.lastrowid,ref_code=ref)

@app.patch('/api/admin/providers/<int:pid>')
@admin_required
def admin_provider_update(pid):
    data=request.get_json(silent=True) or {}; p=db().execute('SELECT * FROM providers WHERE id=?',(pid,)).fetchone()
    if not p:return jsonify(error='Provider not found.'),404
    fields=[]; vals=[]
    for key in ('name','phone','role'):
        if key in data:
            if key=='role' and data[key] not in ('Rider','Driver','Mover'): return jsonify(error='Invalid role.'),400
            fields.append(f'{key}=?'); vals.append(data[key])
    if 'active' in data: fields.append('active=?'); vals.append(1 if data['active'] else 0)
    if data.get('password'): fields.append('password_hash=?'); vals.append(generate_password_hash(data['password']))
    if fields:
        vals.append(pid); db().execute(f'UPDATE providers SET {", ".join(fields)} WHERE id=?',vals); db().commit()
    audit('admin',None,'update_provider',str(pid)); return jsonify(ok=True)

@app.get('/api/admin/users')
@admin_required
def admin_users():
    rows=db().execute('SELECT id,name,identifier,phone,active,created_at,last_seen_at FROM users ORDER BY id DESC LIMIT 200').fetchall(); return jsonify(items=[dict(r) for r in rows])

@app.patch('/api/admin/users/<int:uid>')
@admin_required
def admin_user_update(uid):
    data=request.get_json(silent=True) or {}
    user=db().execute('SELECT id FROM users WHERE id=?',(uid,)).fetchone()
    if not user:return jsonify(error='User not found.'),404
    fields=[]; vals=[]
    if 'active' in data: fields.append('active=?'); vals.append(1 if data['active'] else 0)
    if data.get('password'): fields.append('password_hash=?'); vals.append(generate_password_hash(data['password']))
    if data.get('name'): fields.append('name=?'); vals.append(str(data['name']).strip())
    if fields:
        vals.append(uid);db().execute(f'UPDATE users SET {", ".join(fields)} WHERE id=?',vals);db().commit()
    audit('admin',None,'update_user',str(uid));return jsonify(ok=True)

@app.get('/api/admin/ratings')
@admin_required
def admin_ratings():
    rows=db().execute('SELECT r.*,u.name,u.identifier FROM ratings r LEFT JOIN users u ON u.id=r.user_id ORDER BY r.id DESC LIMIT 200').fetchall();return jsonify(items=[dict(r) for r in rows])

@app.get('/api/admin/audit')
@admin_required
def admin_audit():
    rows=db().execute('SELECT * FROM audit_log ORDER BY id DESC LIMIT 300').fetchall();return jsonify(items=[dict(r) for r in rows])

@app.get('/api/admin/requests')
@admin_required
def admin_requests():
    rows=db().execute('''SELECT r.*, u.name user_name, p.name provider_name, p.role provider_role FROM requests r LEFT JOIN users u ON u.id=r.user_id LEFT JOIN providers p ON p.id=r.provider_id ORDER BY r.id DESC LIMIT 200''').fetchall(); return jsonify(items=[dict(r) for r in rows])

@app.patch('/api/admin/requests/<int:rid>')
@admin_required
def admin_request_update(rid):
    data=request.get_json(silent=True) or {}; status=data.get('status'); provider_id=data.get('provider_id')
    allowed={'New','Available','Coming to you','On trip','Completed','Cancelled'}
    if status not in allowed:return jsonify(error='Invalid status.'),400
    db().execute('UPDATE requests SET status=?, provider_id=?, updated_at=? WHERE id=?',(status,provider_id or None,now_iso(),rid));db().commit();audit('admin',None,'update_request',f'{rid}:{status}');return jsonify(ok=True)

@app.get('/api/admin/complaints')
@admin_required
def admin_complaints():
    rows=db().execute('SELECT * FROM complaints ORDER BY id DESC LIMIT 200').fetchall(); return jsonify(items=[dict(r) for r in rows])

@app.patch('/api/admin/complaints/<int:cid>')
@admin_required
def admin_complaint_update(cid):
    status=(request.get_json(silent=True) or {}).get('status')
    if status not in ('Open','In review','Resolved'):return jsonify(error='Invalid status.'),400
    db().execute('UPDATE complaints SET status=? WHERE id=?',(status,cid));db().commit();return jsonify(ok=True)

@app.get('/api/provider/requests')
@provider_required
def provider_requests():
    role=session['provider_role']; service='O-Ride' if role=='Rider' else ('O-Drive' if role=='Driver' else 'O-Movers')
    rows=db().execute("SELECT r.*,u.name user_name FROM requests r LEFT JOIN users u ON u.id=r.user_id WHERE r.service=? AND r.status IN ('Available','Coming to you','On trip') ORDER BY r.id DESC",(service,)).fetchall();return jsonify(items=[dict(r) for r in rows])

@app.post('/api/provider/requests/<int:rid>/claim')
@provider_required
def claim_request(rid):
    row=db().execute('SELECT service,status FROM requests WHERE id=?',(rid,)).fetchone()
    if not row:return jsonify(error='Request not found.'),404
    expected='O-Ride' if session['provider_role']=='Rider' else ('O-Drive' if session['provider_role']=='Driver' else 'O-Movers')
    if row['service']!=expected:return jsonify(error='This request belongs to another provider role.'),403
    if row['status'] not in ('New','Available'):return jsonify(error='Request is no longer available.'),409
    db().execute("UPDATE requests SET provider_id=?,status='Coming to you',updated_at=? WHERE id=?",(session['provider_id'],now_iso(),rid));db().commit();return jsonify(ok=True)

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'): return jsonify(error='Not found'),404
    return render_template('error.html',code=404,message='That O route does not exist.'),404

@app.errorhandler(500)
def server_error(e):
    if request.path.startswith('/api/'): return jsonify(error='O hit an internal error.'),500
    return render_template('error.html',code=500,message='O hit an internal error.'),500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','5000')), debug=os.getenv('FLASK_DEBUG')=='1')
