from __future__ import annotations
import json, math, os, secrets, sqlite3, shutil, uuid, io, re, urllib.parse, urllib.request
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
import hashlib
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode
from flask import Flask, jsonify, redirect, render_template, request, session, url_for, send_file, abort

BASE_DIR = Path(__file__).resolve().parent

def choose_data_dir():
    # O only needs USER_NAME and PASSWORD in Render. Storage location is an
    # implementation detail: use the persistent Render disk when available,
    # otherwise fall back to a writable local instance directory.
    candidates = [Path('/var/data'), BASE_DIR / 'instance']
    last_error = None
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / '.write-test'
            probe.write_text('ok', encoding='utf-8')
            probe.unlink(missing_ok=True)
            return candidate
        except (OSError, PermissionError) as exc:
            last_error = exc
            continue
    raise RuntimeError(f'No writable data directory available: {last_error}')

DATA_DIR = choose_data_dir()
DB_PATH = DATA_DIR / 'o.db'
BACKUP_DIR = DATA_DIR / 'backups'
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Keep session signing out of Render environment variables for now. It is
# deterministically derived from the two requested admin credentials, so the
# app remains easy to deploy while sessions still use a non-human-readable key.
ADMIN_USERNAME = (os.environ.get('USER_NAME') or 'admin').strip()
ADMIN_PASSWORD = os.environ.get('PASSWORD') or 'ChangeMeNow!'
SECRET_KEY = hashlib.sha256((ADMIN_USERNAME + '|' + ADMIN_PASSWORD + '|O-MOBILITY-SESSION-V1').encode('utf-8')).hexdigest()

app = Flask(__name__, template_folder=str(BASE_DIR / 'app' / 'templates'), static_folder=str(BASE_DIR / 'app' / 'static'), static_url_path='/static')
app.secret_key = SECRET_KEY
app.config.update(MAX_CONTENT_LENGTH=5*1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=bool(os.environ.get('RENDER')))
ADMIN_PATH = 'promise212324'

SERVICES = {'bike':'O-Ride','ride':'O-Drive','mover':'O-Movers'}
PROVIDER_PATHS = {'bike':'/O-Rider','ride':'/O-Drive','mover':'/O-Movers'}
STATUS_COLORS = {'available':'orange','assigned':'green','enroute':'green','on_trip':'blue','offline':'gray'}


def now(): return datetime.now(timezone.utc).isoformat()
def get_db():
    c=sqlite3.connect(DB_PATH, timeout=30); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def init_db():
    c=get_db()
    c.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY, role TEXT NOT NULL, name TEXT NOT NULL, phone TEXT UNIQUE NOT NULL,
      username TEXT UNIQUE,
      email TEXT, password_hash TEXT, active INTEGER NOT NULL DEFAULT 1, verified INTEGER NOT NULL DEFAULT 0,
      is_guest INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, last_seen TEXT
    );
    CREATE TABLE IF NOT EXISTS drivers (
      user_id INTEGER PRIMARY KEY REFERENCES users(id), service TEXT NOT NULL DEFAULT 'bike',
      vehicle_label TEXT, plate TEXT, license_no TEXT, status TEXT NOT NULL DEFAULT 'offline',
      lat REAL, lng REAL, rating REAL NOT NULL DEFAULT 5.0, jobs INTEGER NOT NULL DEFAULT 0,
      joined_code TEXT UNIQUE, referral_count INTEGER NOT NULL DEFAULT 0, deactivated_reason TEXT
    );
    CREATE TABLE IF NOT EXISTS requests (
      id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES users(id), service TEXT NOT NULL,
      pickup TEXT NOT NULL, destination TEXT NOT NULL, pickup_lat REAL, pickup_lng REAL,
      dest_lat REAL, dest_lng REAL, distance_km REAL NOT NULL DEFAULT 0, fare REAL NOT NULL DEFAULT 0,
      customer_offer REAL, status TEXT NOT NULL DEFAULT 'searching', driver_id INTEGER REFERENCES users(id),
      payment_method TEXT NOT NULL DEFAULT 'cash', payment_status TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL, accepted_at TEXT, started_at TEXT, completed_at TEXT, cancelled_at TEXT,
      cancel_reason TEXT, notes TEXT, contact_phone TEXT
    );
    CREATE TABLE IF NOT EXISTS ratings (
      id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL REFERENCES requests(id), customer_id INTEGER REFERENCES users(id),
      driver_id INTEGER REFERENCES users(id), app_rating INTEGER, rider_rating INTEGER, comment TEXT, created_at TEXT NOT NULL,
      UNIQUE(request_id)
    );
    CREATE TABLE IF NOT EXISTS complaints (
      id INTEGER PRIMARY KEY, request_id INTEGER, user_id INTEGER NOT NULL REFERENCES users(id),
      category TEXT NOT NULL, details TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', admin_note TEXT,
      created_at TEXT NOT NULL, resolved_at TEXT
    );
    CREATE TABLE IF NOT EXISTS notifications (
      id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL, title TEXT NOT NULL,
      body TEXT NOT NULL, request_id INTEGER, read_at TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS audits (
      id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT NOT NULL, entity_type TEXT, entity_id INTEGER,
      details TEXT, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS visitors (
      id INTEGER PRIMARY KEY, visitor_token TEXT UNIQUE NOT NULL, user_id INTEGER REFERENCES users(id),
      ip_address TEXT, device_model TEXT, device_family TEXT, platform TEXT, platform_version TEXT,
      browser_family TEXT, browser_version TEXT, is_mobile INTEGER DEFAULT 0, screen_width INTEGER, screen_height INTEGER,
      lat REAL, lng REAL, accuracy REAL, location_updated_at TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS visit_events (
      id INTEGER PRIMARY KEY, visitor_token TEXT NOT NULL, user_id INTEGER REFERENCES users(id),
      path TEXT NOT NULL, service TEXT, role_hint TEXT, entered_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS pwa_installs (
      id INTEGER PRIMARY KEY, visitor_token TEXT NOT NULL, user_id INTEGER REFERENCES users(id),
      platform TEXT, device_model TEXT, installed_at TEXT NOT NULL, UNIQUE(visitor_token)
    );
    CREATE TABLE IF NOT EXISTS app_errors (
      id INTEGER PRIMARY KEY, source TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'error',
      route TEXT, message TEXT NOT NULL, details TEXT, user_id INTEGER REFERENCES users(id),
      visitor_token TEXT, created_at TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0
    );
    ''')
    # Lightweight migrations for databases created by earlier O versions.
    cols={r['name'] for r in c.execute('PRAGMA table_info(users)').fetchall()}
    if 'is_guest' not in cols: c.execute('ALTER TABLE users ADD COLUMN is_guest INTEGER NOT NULL DEFAULT 0')
    if 'username' not in cols:
        c.execute('ALTER TABLE users ADD COLUMN username TEXT')
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username) WHERE username IS NOT NULL")
        c.execute('UPDATE users SET username=phone WHERE username IS NULL')
    visitor_cols={r['name'] for r in c.execute('PRAGMA table_info(visitors)').fetchall()}
    if 'location_label' not in visitor_cols: c.execute('ALTER TABLE visitors ADD COLUMN location_label TEXT')
    req_cols={r['name'] for r in c.execute('PRAGMA table_info(requests)').fetchall()}
    if 'contact_phone' not in req_cols: c.execute('ALTER TABLE requests ADD COLUMN contact_phone TEXT')
    defaults={
      'bike_base':'55','bike_per_km':'18','ride_base':'110','ride_per_km':'42',
      'mover_base':'600','mover_per_km':'60','mover_item_fee':'100','mover_helper_fee':'650','platform_commission':'10',
      'otravel_url':'https://otravel-bleg.onrender.com/','support_phone':'','app_name':'O'
    }
    for k,v in defaults.items(): c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',(k,v))
    # Keep admin credentials sourced from Render variables USER_NAME / PASSWORD.
    admin_row=c.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
    if not admin_row:
        c.execute("INSERT INTO users(role,name,phone,username,password_hash,active,verified,created_at) VALUES('admin',?,?,?,?,1,1,?)",('O Admin',ADMIN_USERNAME,ADMIN_USERNAME,generate_password_hash(ADMIN_PASSWORD),now()))
    else:
        c.execute("UPDATE users SET phone=?, username=?, password_hash=?, active=1, verified=1 WHERE id=?",(ADMIN_USERNAME,ADMIN_USERNAME,generate_password_hash(ADMIN_PASSWORD),admin_row['id']))
    c.commit(); c.close()
init_db()

def setting(key, default=''):
    c=get_db(); r=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone(); c.close(); return r['value'] if r else default

def audit(action, entity_type='', entity_id=None, details='', actor_id=None):
    c=get_db(); c.execute('INSERT INTO audits(actor_id,action,entity_type,entity_id,details,created_at) VALUES(?,?,?,?,?,?)',(actor_id,action,entity_type,entity_id,details,now())); c.commit(); c.close()

def notify(user_id, kind, title, body, request_id=None):
    c=get_db(); c.execute('INSERT INTO notifications(user_id,kind,title,body,request_id,created_at) VALUES(?,?,?,?,?,?)',(user_id,kind,title,body,request_id,now())); c.commit(); c.close()

def current_user():
    uid=session.get('uid')
    if not uid: return None
    c=get_db(); u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close(); return u

def has_guest_session():
    gid=session.get('guest_uid')
    if not gid: return False
    c=get_db(); ok=bool(c.execute('SELECT 1 FROM users WHERE id=? AND is_guest=1 AND active=1',(gid,)).fetchone()); c.close(); return ok

def login_required(fn):
    @wraps(fn)
    def w(*a,**kw):
        if not current_user() and not has_guest_session(): return redirect(url_for('login', next=request.path))
        return fn(*a,**kw)
    return w

def admin_required(fn):
    @wraps(fn)
    def w(*a,**kw):
        u=current_user()
        if not u or u['role']!='admin': return redirect(url_for('admin_login'))
        return fn(*a,**kw)
    return w

def haversine(a,b,c,d):
    if None in (a,b,c,d): return 0.0
    R=6371.0; p1=math.radians(a); p2=math.radians(c); dp=math.radians(c-a); dl=math.radians(d-b)
    x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R*2*math.atan2(math.sqrt(x), math.sqrt(1-x))

def fare(service, km, items=0, helpers=0):
    if service=='bike': return max(60, round(float(setting('bike_base','60')) + float(setting('bike_per_km','22'))*max(km,0), -1))
    if service=='ride': return max(150, round(float(setting('ride_base','150')) + float(setting('ride_per_km','48'))*max(km,0), -1))
    return max(700, round(float(setting('mover_base','700')) + float(setting('mover_per_km','70'))*max(km,0) + items*float(setting('mover_item_fee','120')) + helpers*float(setting('mover_helper_fee','700')), -1))

def find_driver(service, lat, lng):
    if lat is None or lng is None: return None
    c=get_db()
    rows=c.execute("SELECT d.*,u.name,u.phone FROM drivers d JOIN users u ON u.id=d.user_id WHERE d.service=? AND u.active=1 AND u.verified=1 AND d.status='available' AND d.lat IS NOT NULL AND d.lng IS NOT NULL",(service,)).fetchall(); c.close()
    ranked=sorted(rows,key=lambda r:haversine(lat,lng,r['lat'],r['lng']))
    return ranked[0] if ranked else None

def client_ip():
    forwarded=request.headers.get('X-Forwarded-For','').split(',')[0].strip()
    return forwarded or request.remote_addr or ''

def browser_family(ua):
    u=(ua or '').lower()
    checks=[('Edge','edg/'),('Opera','opr/'),('Chrome','chrome/'),('Firefox','firefox/'),('Samsung Internet','samsungbrowser/'),('Safari','safari/')]
    if 'crios/' in u: return 'Chrome iOS'
    if 'fxios/' in u: return 'Firefox iOS'
    for name, token in checks:
        if token in u: return name
    return 'Other'

def platform_family(ua):
    u=(ua or '').lower()
    if 'windows' in u: return 'Windows'
    if 'android' in u: return 'Android'
    if 'iphone' in u or 'ipad' in u or 'ios' in u: return 'iOS'
    if 'mac os' in u or 'macintosh' in u: return 'macOS'
    if 'linux' in u: return 'Linux'
    return 'Other'

def upsert_visitor(data):
    token=session.get('visitor_token') or secrets.token_urlsafe(24); session['visitor_token']=token
    ua=request.headers.get('User-Agent','')
    model=(data.get('device_model') or request.headers.get('Sec-CH-UA-Model') or '').strip()
    platform=(data.get('platform') or request.headers.get('Sec-CH-UA-Platform') or platform_family(ua)).strip('" ')
    browser=(data.get('browser_family') or browser_family(ua)).strip()
    is_mobile=1 if bool(data.get('is_mobile')) or 'mobile' in ua.lower() else 0
    path=str(data.get('path') or request.path or '/')[:300]
    svc=(data.get('service') or '').strip()[:30] or None
    role_hint=(data.get('role_hint') or ('customer' if current_user() and current_user()['role']=='customer' else ('provider' if current_user() and current_user()['role']=='driver' else 'visitor')))[:30]
    c=get_db(); existing=c.execute('SELECT id FROM visitors WHERE visitor_token=?',(token,)).fetchone()
    values=(client_ip(),model,data.get('device_family') or ('Phone' if is_mobile else 'Computer'),platform,data.get('platform_version') or '',browser,data.get('browser_version') or '',is_mobile,data.get('screen_width'),data.get('screen_height'),now())
    uid=current_user()['id'] if current_user() else None
    if existing:
        c.execute("UPDATE visitors SET user_id=?,ip_address=?,device_model=COALESCE(NULLIF(?,''),device_model),device_family=?,platform=?,platform_version=?,browser_family=?,browser_version=?,is_mobile=?,screen_width=?,screen_height=?,last_seen=? WHERE id=?",(uid,)+values+(existing['id'],))
    else:
        c.execute("INSERT INTO visitors(visitor_token,user_id,ip_address,device_model,device_family,platform,platform_version,browser_family,browser_version,is_mobile,screen_width,screen_height,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(token,uid,*values[:-1],values[-1],values[-1]))
    c.execute('INSERT INTO visit_events(visitor_token,user_id,path,service,role_hint,entered_at) VALUES(?,?,?,?,?,?)',(token,uid,path,svc,role_hint,now()))
    c.commit(); c.close();
    return token

def get_guest_user(contact_phone=''):
    uid=session.get('guest_uid')
    c=get_db()
    if uid:
        u=c.execute('SELECT * FROM users WHERE id=? AND is_guest=1',(uid,)).fetchone()
        if u:
            if contact_phone and u['phone'].startswith('guest-'):
                try: c.execute('UPDATE users SET phone=? WHERE id=?',(contact_phone,u['id']))
                except sqlite3.IntegrityError: pass
                c.commit(); u=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone()
            c.close(); return u
    phone=(contact_phone.strip() if contact_phone else '') or ('guest-'+uuid.uuid4().hex)
    c.execute("INSERT INTO users(role,name,phone,password_hash,active,verified,is_guest,created_at) VALUES('customer','Guest',?,?,1,0,1,?)",(phone,None,now()))
    uid=c.execute('SELECT last_insert_rowid() x').fetchone()['x']; c.commit(); u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close(); session['guest_uid']=uid; return u

def mask_phone(phone):
    if not phone: return ''
    return phone[:4]+'***'+phone[-2:]

@app.after_request
def security_headers(resp):
    resp.headers['X-Content-Type-Options']='nosniff'; resp.headers['X-Frame-Options']='SAMEORIGIN'; resp.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    if resp.status_code >= 500 or (resp.status_code in (404,405) and not request.path.startswith('/static/') and request.path not in ('/admin',)):
        try:
            c=get_db(); c.execute('INSERT INTO app_errors(source,severity,route,message,details,user_id,visitor_token,created_at) VALUES(?,?,?,?,?,?,?,?)',('server','error' if resp.status_code>=500 else 'warning',request.path,f'HTTP {resp.status_code}',request.method,current_user()['id'] if current_user() else None,session.get('visitor_token'),now())); c.commit(); c.close()
        except Exception: pass
    return resp

@app.route('/health')
def health(): return jsonify(ok=True, service='O Mobility', time=now())

@app.route('/robots.txt')
def robots(): return app.response_class('User-agent: *\nAllow: /\nSitemap: '+url_for('sitemap',_external=True)+'\n',mimetype='text/plain')
@app.route('/sitemap.xml')
def sitemap():
    urls=[url_for('home',_external=True),url_for('services_page',_external=True),url_for('service_page',service='bike',_external=True),url_for('service_page',service='ride',_external=True),url_for('service_page',service='mover',_external=True),url_for('provider_ride',_external=True),url_for('provider_drive',_external=True),url_for('provider_movers',_external=True)]
    return app.response_class('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>{u}</loc></url>' for u in urls)+'</urlset>',mimetype='application/xml')

@app.route('/sw.js')
def root_service_worker():
    # A root-scoped worker controls the whole O PWA, not only /static/.
    return app.send_static_file('sw.js')

@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('logo.svg')

@app.route('/pulse_receiver', methods=['POST'])
def pulse_receiver():
    # Compatibility endpoint for harmless uptime/pulse senders. O does not need
    # the external pulse service for core operation.
    return jsonify(ok=True)

@app.route('/')
def home():
    upsert_visitor({})
    return render_template('home.html',otravel_url='https://otravel-bleg.onrender.com/',user=current_user())

@app.route('/services')
def services_page():
    upsert_visitor({'service': ''})
    return render_template('services.html',otravel_url='https://otravel-bleg.onrender.com/',user=current_user())

@app.route('/qr')
def qr_code():
    target=request.host_url.rstrip('/') + '/'
    ref=(request.args.get('ref') or '').strip()
    if ref: target += '?ref=' + ref
    img=qrcode.make(target)
    buf=io.BytesIO(); img.save(buf,format='PNG'); buf.seek(0)
    return send_file(buf,mimetype='image/png',download_name='O-share.png')

def nominatim_json(path):
    url='https://nominatim.openstreetmap.org'+path
    req=urllib.request.Request(url,headers={'User-Agent':'O-Mobility/1.0 (location search)'})
    with urllib.request.urlopen(req,timeout=8) as r:
        return json.loads(r.read().decode('utf-8'))

@app.route('/api/geocode/search')
def geocode_search():
    q=(request.args.get('q') or '').strip()
    if not q: return jsonify(items=[])
    try:
        rows=nominatim_json('/search?format=jsonv2&limit=5&addressdetails=1&q='+urllib.parse.quote(q))
        return jsonify(items=[{'lat':x.get('lat'),'lng':x.get('lon'),'name':x.get('display_name','')} for x in rows])
    except Exception:
        return jsonify(items=[])

@app.route('/api/geocode/reverse')
def geocode_reverse():
    try:
        lat=float(request.args.get('lat')); lng=float(request.args.get('lng'))
    except (TypeError,ValueError):
        return jsonify(name='')
    try:
        x=nominatim_json('/reverse?format=jsonv2&lat='+urllib.parse.quote(str(lat))+'&lon='+urllib.parse.quote(str(lng)))
        return jsonify(name=x.get('display_name',''))
    except Exception:
        return jsonify(name='')

@app.route('/api/visitor/context',methods=['POST'])
def visitor_context():
    d=request.get_json(silent=True) or {}
    upsert_visitor(d)
    # Store consented browser geolocation only; no location is guessed from the browser name.
    if d.get('lat') is not None and d.get('lng') is not None:
        try:
            c=get_db(); token=session.get('visitor_token'); c.execute('UPDATE visitors SET lat=?,lng=?,accuracy=?,location_label=?,location_updated_at=?,last_seen=? WHERE visitor_token=?',(float(d['lat']),float(d['lng']),float(d.get('accuracy') or 0),str(d.get('location_label') or '')[:240],now(),now(),token)); c.commit(); c.close()
        except (TypeError,ValueError): pass
    return jsonify(ok=True)
@app.route('/api/pwa/install',methods=['POST'])
def pwa_install():
    d=request.get_json(silent=True) or {}; token=session.get('visitor_token') or upsert_visitor(d)
    c=get_db();
    try:
        c.execute('INSERT OR IGNORE INTO pwa_installs(visitor_token,user_id,platform,device_model,installed_at) VALUES(?,?,?,?,?)',(token,current_user()['id'] if current_user() else None,str(d.get('platform') or '')[:80],str(d.get('device_model') or '')[:120],now())); c.commit()
    finally: c.close()
    audit('pwa_install','visitor',None,details=f'platform={d.get("platform","")};model={d.get("device_model","")}',actor_id=current_user()['id'] if current_user() else None)
    return jsonify(ok=True)

@app.route('/api/client-error',methods=['POST'])
def client_error():
    d=request.get_json(silent=True) or {}; msg=str(d.get('message') or 'Client error')[:500]; details=str(d.get('details') or '')[:3000]
    try:
        c=get_db(); c.execute('INSERT INTO app_errors(source,severity,route,message,details,user_id,visitor_token,created_at) VALUES(?,?,?,?,?,?,?,?)',('browser',str(d.get('severity') or 'error')[:20],str(d.get('route') or request.path)[:300],msg,details,current_user()['id'] if current_user() else None,session.get('visitor_token'),now())); c.commit(); c.close()
    except Exception: pass
    return jsonify(ok=True)

@app.route('/service/<service>')
def service_page(service):
    if service not in SERVICES: return 'Not found',404
    upsert_visitor({})
    u=current_user()
    recent_successes=[]
    if u and u['role']=='customer':
        c=get_db()
        recent_successes=c.execute(
            "SELECT id,pickup,destination,fare,completed_at FROM requests WHERE customer_id=? AND service=? AND status='completed' ORDER BY completed_at DESC, id DESC LIMIT 4",
            (u['id'],service)
        ).fetchall()
        c.close()
    return render_template('service.html',service=service,name=SERVICES[service],user=current_user(),recent_successes=recent_successes)

@app.route('/login',methods=['GET','POST'])
def login():
    upsert_visitor({})
    if request.method=='POST':
        phone=request.form.get('phone','').strip(); pwd=request.form.get('password','')
        c=get_db(); u=c.execute('SELECT * FROM users WHERE phone=? OR username=? LIMIT 1',(phone,phone)).fetchone(); c.close()
        if u and u['active'] and u['password_hash'] and check_password_hash(u['password_hash'],pwd):
            session['uid']=u['id']; audit('login','user',u['id'],actor_id=u['id']); nxt=request.form.get('next') or request.args.get('next') or ''
            if nxt.startswith('/') and not nxt.startswith('//') and nxt != '/admin': return redirect(nxt)
            return redirect(url_for('dashboard'))
        nxt=request.form.get('next') or request.args.get('next',''); prov=bool(request.args.get('provider')) or any(x in nxt for x in ('/O-Rider','/O-Ride','/O-Drive','/O-drive','/O-Movers')); pname='O Partner'
        if '/O-Rider' in nxt or '/O-Ride' in nxt: pname='O-Ride'
        elif '/O-Drive' in nxt or '/O-drive' in nxt: pname='O-Drive'
        elif '/O-Movers' in nxt: pname='O-Movers'
        return render_template('login.html',error='Invalid credentials or inactive account.',next=nxt,provider=prov,provider_name=pname)
    nxt=request.args.get('next','')
    prov=bool(request.args.get('provider')) or any(x in nxt for x in ('/O-Rider','/O-Ride','/O-Drive','/O-drive','/O-Movers'))
    provider_name='O Partner'
    if '/O-Rider' in nxt or '/O-Ride' in nxt: provider_name='O-Ride'
    elif '/O-Drive' in nxt or '/O-drive' in nxt: provider_name='O-Drive'
    elif '/O-Movers' in nxt: provider_name='O-Movers'
    return render_template('login.html',error=None,next=nxt,provider=prov,provider_name=provider_name)
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('home'))
@app.route('/dashboard')
@login_required
def dashboard():
    u=current_user();
    if u['role']=='admin': return redirect(url_for('admin'))
    if u['role']=='driver': return redirect(url_for('driver_dashboard'))
    c=get_db(); rides=c.execute('SELECT r.*,d.name driver_name FROM requests r LEFT JOIN users d ON d.id=r.driver_id WHERE r.customer_id=? ORDER BY r.id DESC LIMIT 20',(u['id'],)).fetchall(); c.close()
    upsert_visitor({})
    return render_template('customer_dashboard.html',user=u,rides=rides,share_ref=str(u['id']))

@app.route('/join',methods=['GET','POST'])
def join():
    return redirect(url_for('home'))

@app.route('/api/estimate',methods=['POST'])
def api_estimate():
    data=request.get_json() or {}; service=data.get('service','bike'); km=float(data.get('distance_km') or 0); items=int(data.get('items') or 0); helpers=int(data.get('helpers') or 0)
    return jsonify(service=service, distance_km=km, fare=fare(service,km,items,helpers), commission_pct=float(setting('platform_commission','10')))

@app.route('/api/request',methods=['POST'])
def api_request():
    u=current_user()
    if not u or u['role']!='customer':
        u=get_guest_user(d.get('contact_phone','') if (d:=request.get_json(silent=True) or {}) else '')
        try:
            c=get_db(); c.execute('UPDATE visitors SET user_id=? WHERE visitor_token=?',(u['id'],session.get('visitor_token'))); c.commit(); c.close()
        except Exception:
            pass
    else:
        d=request.get_json(silent=True) or {}
    d=d or {}
    service=d.get('service');
    if service not in SERVICES: return jsonify(error='Invalid service.'),400
    pickup=(d.get('pickup') or '').strip(); dest=(d.get('destination') or '').strip()
    plat=d.get('pickup_lat'); plng=d.get('pickup_lng'); dlat=d.get('dest_lat'); dlng=d.get('dest_lng')
    if not pickup or not dest: return jsonify(error='Pickup and destination are required.'),400
    if plat is None or plng is None: return jsonify(error='Please turn on your location so O can find the right nearby partner.'),400
    km=haversine(float(plat),float(plng),float(dlat),float(dlng)) if None not in (plat,plng,dlat,dlng) else float(d.get('distance_km') or 0)
    amount=fare(service,km,int(d.get('items') or 0),int(d.get('helpers') or 0))
    contact_phone=(d.get('contact_phone') or '').strip() or None
    c=get_db(); cur=c.execute('INSERT INTO requests(customer_id,service,pickup,destination,pickup_lat,pickup_lng,dest_lat,dest_lng,distance_km,fare,customer_offer,payment_method,notes,contact_phone,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(u['id'],service,pickup,dest,plat,plng,dlat,dlng,km,amount,d.get('customer_offer'),d.get('payment_method','cash'),d.get('notes',''),contact_phone,now())); rid=cur.lastrowid; c.commit(); c.close()
    drv=find_driver(service,float(plat) if plat is not None else None,float(plng) if plng is not None else None)
    if drv:
        c=get_db(); c.execute("UPDATE requests SET driver_id=?,status='assigned',accepted_at=NULL WHERE id=?",(drv['user_id'],rid)); c.commit(); c.close(); notify(drv['user_id'],'ride','New O request',f'{SERVICES[service]} request near you: {pickup}',rid)
    audit('request_created','request',rid,f'service={service};fare={amount};driver={drv["user_id"] if drv else None}',u['id'])
    return jsonify(ok=True,request_id=rid,fare=amount,status='assigned' if drv else 'searching',driver={'name':drv['name'],'phone':mask_phone(drv['phone'])} if drv else None)

@app.route('/api/request/<int:rid>')
@login_required
def request_status(rid):
    u=current_user() or get_guest_user(); c=get_db(); r=c.execute('SELECT r.*,d.name driver_name FROM requests r LEFT JOIN users d ON d.id=r.driver_id WHERE r.id=? AND (r.customer_id=? OR r.driver_id=?)',(rid,u['id'],u['id'])).fetchone(); c.close()
    if not r: return jsonify(error='Not found'),404
    return jsonify(request=dict(r))

@app.route('/api/request/<int:rid>/action',methods=['POST'])
@login_required
def request_action(rid):
    u=current_user() or get_guest_user(); action=(request.get_json() or {}).get('action'); c=get_db(); r=c.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
    if not r: c.close(); return jsonify(error='Not found'),404
    if u['role']=='driver' and r['driver_id']==u['id']:
        if not u['active'] or not u['verified']:
            c.close(); return jsonify(error='Your O partner account is not active or verified.'),403
        allowed={'accept':'accepted','reject':'searching','start':'on_trip','complete':'completed','cancel':'cancelled'}
        if action not in allowed: c.close(); return jsonify(error='Invalid action'),400
        ns=allowed[action]
        if action=='reject':
            c.execute("UPDATE requests SET driver_id=NULL,status='searching' WHERE id=?",(rid,))
            c.commit()
            next_driver=find_driver(r['service'], r['pickup_lat'], r['pickup_lng'])
            if next_driver:
                c.execute("UPDATE requests SET driver_id=?,status='assigned' WHERE id=?",(next_driver['user_id'],rid)); c.commit()
                notify(next_driver['user_id'],'ride','New O request',f'{SERVICES[r['service']]} request near you: {r['pickup']}',rid)
        elif action=='accept': c.execute("UPDATE requests SET status='accepted',accepted_at=? WHERE id=?",(now(),rid))
        elif action=='start': c.execute("UPDATE requests SET status='on_trip',started_at=? WHERE id=?",(now(),rid))
        elif action=='complete': c.execute("UPDATE requests SET status='completed',completed_at=?,payment_status='pending' WHERE id=?",(now(),rid)); c.execute('UPDATE drivers SET status=\'available\',jobs=jobs+1 WHERE user_id=?',(u['id'],))
        elif action=='cancel': c.execute("UPDATE requests SET status='cancelled',cancelled_at=?,cancel_reason='driver' WHERE id=?",(now(),rid)); c.execute("UPDATE drivers SET status='available' WHERE user_id=?",(u['id'],))
        c.commit(); c.close(); notify(r['customer_id'],'ride','O ride update',f'Your request #{rid} is now {ns.replace("_"," ")}.',rid); audit('request_action','request',rid,action,u['id']); return jsonify(ok=True,status=ns)
    if u['role']=='customer' and r['customer_id']==u['id'] and action=='cancel' and r['status'] in ('searching','assigned','accepted'):
        c.execute("UPDATE requests SET status='cancelled',cancelled_at=?,cancel_reason='customer' WHERE id=?",(now(),rid));
        if r['driver_id']: c.execute("UPDATE drivers SET status='available' WHERE user_id=?",(r['driver_id'],))
        c.commit(); c.close(); audit('request_cancelled','request',rid,'customer',u['id']); return jsonify(ok=True,status='cancelled')
    c.close(); return jsonify(error='Not permitted'),403

@app.route('/api/notifications')
@login_required
def notifications():
    u=current_user(); c=get_db(); rows=c.execute('SELECT * FROM notifications WHERE user_id=? AND read_at IS NULL ORDER BY id DESC LIMIT 20',(u['id'],)).fetchall(); c.close(); return jsonify(items=[dict(r) for r in rows])
@app.route('/api/notifications/read',methods=['POST'])
@login_required
def notifications_read():
    u=current_user(); c=get_db(); c.execute('UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL',(now(),u['id'])); c.commit(); c.close(); return jsonify(ok=True)

def provider_entry(service):
    u=current_user()
    target=PROVIDER_PATHS[service]
    if not u:
        return redirect(url_for('login', next=target+'?provider=1'))
    if u['role']!='driver':
        abort(404)
    c=get_db(); d=c.execute('SELECT d.*,u.name,u.phone,u.verified,u.active FROM drivers d JOIN users u ON u.id=d.user_id WHERE d.user_id=?',(u['id'],)).fetchone(); c.close()
    if not d or d['service']!=service or not d['active']:
        abort(404)
    return driver_dashboard_view(d)

def driver_dashboard_view(d):
    u=current_user()
    c=get_db()
    jobs=c.execute("SELECT r.*,u.name customer_name FROM requests r JOIN users u ON u.id=r.customer_id WHERE r.driver_id=? AND r.service=? ORDER BY CASE r.status WHEN 'assigned' THEN 0 WHEN 'accepted' THEN 1 WHEN 'on_trip' THEN 2 ELSE 3 END, r.id DESC LIMIT 40",(u['id'],d['service'])).fetchall()
    pending=sum(1 for j in jobs if j['status']=='assigned')
    completed=c.execute("SELECT COUNT(*) n FROM requests WHERE driver_id=? AND service=? AND status='completed'",(u['id'],d['service'])).fetchone()['n']
    earnings=c.execute("SELECT COALESCE(SUM(fare),0) n FROM requests WHERE driver_id=? AND service=? AND status='completed'",(u['id'],d['service'])).fetchone()['n']
    c.close()
    return render_template('driver_dashboard.html',user=u,driver=d,jobs=jobs,provider_path=PROVIDER_PATHS[d['service']],service_name=SERVICES[d['service']],pending=pending,completed=completed,earnings=earnings)

@app.route('/O-Rider')
@app.route('/O-Ride')
def provider_ride():
    return provider_entry('bike')

@app.route('/O-Drive')
@app.route('/O-drive')
def provider_drive():
    return provider_entry('ride')

@app.route('/O-Movers')
def provider_movers():
    return provider_entry('mover')

@app.route('/driver')
def driver_dashboard_legacy():
    u=current_user()
    if not u or u['role']!='driver': return redirect(url_for('login'))
    c=get_db(); d=c.execute('SELECT * FROM drivers WHERE user_id=?',(u['id'],)).fetchone(); c.close()
    if not d: abort(404)
    return redirect(PROVIDER_PATHS.get(d['service'],'/'))
@app.route('/api/driver/presence',methods=['POST'])
@login_required
def driver_presence():
    u=current_user();
    if u['role']!='driver' or not u['active'] or not u['verified']: return jsonify(error='Your O partner account is not active or verified.'),403
    d=request.get_json() or {}; status=d.get('status','offline'); lat=d.get('lat'); lng=d.get('lng')
    if status not in ('available','offline','on_trip'): return jsonify(error='Invalid status'),400
    c=get_db(); c.execute('UPDATE drivers SET status=?,lat=?,lng=? WHERE user_id=?',(status,lat,lng,u['id'])); c.execute('UPDATE users SET last_seen=? WHERE id=?',(now(),u['id'])); c.commit(); c.close(); return jsonify(ok=True,status=status)

@app.route('/api/request/<int:rid>/rate',methods=['POST'])
@login_required
def rate_request(rid):
    u=current_user() or get_guest_user(); d=request.get_json() or {}; app_rating=max(1,min(5,int(d.get('app_rating') or 0))); rider_rating=d.get('rider_rating'); rider_rating=max(1,min(5,int(rider_rating))) if rider_rating else None
    c=get_db(); r=c.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone();
    if not r or r['customer_id']!=u['id'] or r['status']!='completed': c.close(); return jsonify(error='Rating unavailable'),400
    try:
        c.execute('INSERT INTO ratings(request_id,customer_id,driver_id,app_rating,rider_rating,comment,created_at) VALUES(?,?,?,?,?,?,?)',(rid,u['id'],r['driver_id'],app_rating,rider_rating,d.get('comment',''),now()))
        if r['driver_id'] and rider_rating:
            avg=c.execute('SELECT AVG(rider_rating) x FROM ratings WHERE driver_id=? AND rider_rating IS NOT NULL',(r['driver_id'],)).fetchone()['x'] or 5
            c.execute('UPDATE drivers SET rating=? WHERE user_id=?',(round(avg,2),r['driver_id']))
        c.commit(); c.close(); audit('rating_created','request',rid,actor_id=u['id']); return jsonify(ok=True)
    except sqlite3.IntegrityError: c.close(); return jsonify(error='Already rated'),409

@app.route('/complaints',methods=['GET','POST'])
@login_required
def complaints():
    u=current_user(); c=get_db()
    if request.method=='POST':
        rid=request.form.get('request_id') or None; cat=request.form.get('category','other'); details=request.form.get('details','').strip()
        if details: c.execute('INSERT INTO complaints(request_id,user_id,category,details,created_at) VALUES(?,?,?,?,?)',(rid,u['id'],cat,details,now())); c.commit(); audit('complaint_created','request',rid,cat, u['id'])
    rows=c.execute('SELECT * FROM complaints WHERE user_id=? ORDER BY id DESC',(u['id'],)).fetchall(); c.close(); return render_template('complaints.html',rows=rows,user=u)

@app.route('/promise212324',methods=['GET','POST'])
def admin_login():
    u=current_user()
    if u and u['role']=='admin': return redirect(url_for('admin'))
    if request.method=='POST':
        username=request.form.get('username','').strip()
        password=request.form.get('password','')
        c=get_db(); u=c.execute("SELECT * FROM users WHERE role='admin' LIMIT 1").fetchone(); c.close()
        if u and username==ADMIN_USERNAME and password==ADMIN_PASSWORD and u['active']:
            session['uid']=u['id']; audit('admin_login','user',u['id'],actor_id=u['id']); return redirect(url_for('admin'))
        return render_template('admin_login.html',error='Invalid control-room credentials.')
    return render_template('admin_login.html',error=None,admin_path=ADMIN_PATH)

@app.route('/admin')
def admin_public_block():
    return abort(404)

@app.route('/promise212324/api/live')
@admin_required
def admin_live():
    c=get_db(); rows=c.execute("SELECT d.user_id,d.service,d.status,d.lat,d.lng,d.rating,u.name,u.phone,u.active,u.verified FROM drivers d JOIN users u ON u.id=d.user_id WHERE u.active=1 AND d.lat IS NOT NULL AND d.lng IS NOT NULL").fetchall(); c.close(); return jsonify(items=[dict(r) for r in rows])

@app.route('/promise212324/api/visitors')
@admin_required
def admin_visitors():
    c=get_db(); rows=c.execute("""SELECT v.*,u.name,u.phone,
      (SELECT ve.service FROM visit_events ve WHERE ve.visitor_token=v.visitor_token ORDER BY ve.id DESC LIMIT 1) last_service,
      (SELECT r.service FROM requests r WHERE r.customer_id=v.user_id ORDER BY r.id DESC LIMIT 1) last_request_service,
      (SELECT r.status FROM requests r WHERE r.customer_id=v.user_id ORDER BY r.id DESC LIMIT 1) last_request_status,
      CASE WHEN u.role='driver' THEN 'Partner' WHEN u.role='customer' AND u.is_guest=1 THEN 'Guest customer' WHEN u.role='customer' THEN 'Customer' WHEN u.role='admin' THEN 'Admin' ELSE 'Visitor' END person_type
      FROM visitors v LEFT JOIN users u ON u.id=v.user_id ORDER BY v.last_seen DESC LIMIT 200""").fetchall(); c.close();
    out=[]
    labels={'bike':'O-Ride','ride':'O-Drive','mover':'O-Movers'}
    for r in rows:
        d=dict(r); d['service_name']=labels.get(d.get('last_service'), d.get('last_service') or 'Browsing O'); out.append(d)
    return jsonify(items=out)

@app.route('/promise212324/api/service/<service>')
@admin_required
def admin_service(service):
    if service not in SERVICES: return jsonify(error='Unknown service'),404
    c=get_db()
    drivers=c.execute("SELECT d.user_id,d.service,d.status,d.lat,d.lng,d.rating,u.name,u.phone,u.active,u.verified FROM drivers d JOIN users u ON u.id=d.user_id WHERE d.service=? AND u.active=1",(service,)).fetchall()
    requests=c.execute("SELECT r.id,r.pickup,r.destination,r.fare,r.status,r.created_at,u.name customer_name,d.name driver_name FROM requests r JOIN users u ON u.id=r.customer_id LEFT JOIN users d ON d.id=r.driver_id WHERE r.service=? ORDER BY r.id DESC LIMIT 100",(service,)).fetchall()
    c.close()
    return jsonify(service=service,drivers=[dict(x) for x in drivers],requests=[dict(x) for x in requests])

@app.route('/promise212324/control')
@admin_required
def admin():
    c=get_db()
    today=datetime.now(timezone.utc).date().isoformat()
    stats={
      'drivers':c.execute("SELECT COUNT(*) n FROM users WHERE role='driver'").fetchone()['n'],
      'customers':c.execute("SELECT COUNT(*) n FROM users WHERE role='customer' AND is_guest=0").fetchone()['n'],
      'guests':c.execute("SELECT COUNT(*) n FROM users WHERE role='customer' AND is_guest=1").fetchone()['n'],
      'active_drivers':c.execute("SELECT COUNT(*) n FROM drivers d JOIN users u ON u.id=d.user_id WHERE u.active=1 AND d.status='available'").fetchone()['n'],
      'open_requests':c.execute("SELECT COUNT(*) n FROM requests WHERE status IN ('searching','assigned','accepted','on_trip')").fetchone()['n'],
      'completed':c.execute("SELECT COUNT(*) n FROM requests WHERE status='completed'").fetchone()['n'],
      'complaints':c.execute("SELECT COUNT(*) n FROM complaints WHERE status='open'").fetchone()['n'],
      'visitors':c.execute("SELECT COUNT(*) n FROM visitors").fetchone()['n'],
      'today_visitors':c.execute("SELECT COUNT(*) n FROM visitors WHERE substr(first_seen,1,10)=?",(today,)).fetchone()['n'],
      'pwa_installs':c.execute("SELECT COUNT(*) n FROM pwa_installs").fetchone()['n'],
      'today_installs':c.execute("SELECT COUNT(*) n FROM pwa_installs WHERE substr(installed_at,1,10)=?",(today,)).fetchone()['n'],
      'app_errors':c.execute("SELECT COUNT(*) n FROM app_errors WHERE resolved=0").fetchone()['n'],
    }
    service_interest={}
    for svc,label in SERVICES.items(): service_interest[label]=c.execute("SELECT COUNT(*) n FROM visit_events WHERE service=?",(svc,)).fetchone()['n']
    drivers=c.execute("SELECT d.*,u.name,u.phone,u.active,u.verified,u.created_at FROM drivers d JOIN users u ON u.id=d.user_id ORDER BY u.id DESC").fetchall()
    customers=c.execute("SELECT id,name,phone,active,is_guest,created_at,last_seen FROM users WHERE role='customer' ORDER BY id DESC LIMIT 150").fetchall()
    requests=c.execute("SELECT r.*,u.name customer_name,d.name driver_name FROM requests r JOIN users u ON u.id=r.customer_id LEFT JOIN users d ON d.id=r.driver_id ORDER BY r.id DESC LIMIT 100").fetchall()
    complaints=c.execute("SELECT c.*,u.name FROM complaints c JOIN users u ON u.id=c.user_id ORDER BY c.id DESC LIMIT 50").fetchall()
    visitors=c.execute("SELECT v.*,u.name,u.phone,u.role,u.is_guest, CASE WHEN u.role='driver' THEN 'Partner' WHEN u.role='customer' AND u.is_guest=1 THEN 'Guest customer' WHEN u.role='customer' THEN 'Customer' WHEN u.role='admin' THEN 'Admin' ELSE 'Visitor' END person_type FROM visitors v LEFT JOIN users u ON u.id=v.user_id ORDER BY v.last_seen DESC LIMIT 150").fetchall()
    errors=c.execute("SELECT e.*,u.name FROM app_errors e LEFT JOIN users u ON u.id=e.user_id WHERE e.resolved=0 ORDER BY e.id DESC LIMIT 100").fetchall()
    settings={k:setting(k) for k in ['bike_base','bike_per_km','ride_base','ride_per_km','mover_base','mover_per_km','mover_item_fee','mover_helper_fee','platform_commission','otravel_url']}
    c.close()
    return render_template('admin.html',stats=stats,drivers=drivers,customers=customers,requests=requests,complaints=complaints,settings=settings,admin_path=ADMIN_PATH,visitors=visitors,errors=errors,service_interest=service_interest,service_labels=SERVICES)

@app.route('/promise212324/partner/add',methods=['POST'])
@admin_required
def admin_partner_add():
    service=request.form.get('service','bike')
    if service not in SERVICES: return abort(400)
    name=request.form.get('name','').strip(); username=request.form.get('username','').strip(); password=request.form.get('password',''); phone=request.form.get('phone','').strip()
    vehicle=request.form.get('vehicle_label','').strip(); plate=request.form.get('plate','').strip(); license_no=request.form.get('license_no','').strip()
    if not name or not username or len(password)<6 or not phone:
        return redirect(url_for('admin',msg='Complete partner name, username, phone and a 6+ character password.'))
    c=get_db()
    try:
        cur=c.execute("INSERT INTO users(role,name,phone,username,password_hash,active,verified,created_at,last_seen) VALUES('driver',?,?,?,?,1,1,?,?)",(name,phone,username,generate_password_hash(password),now(),now()))
        uid=cur.lastrowid
        code='O'+secrets.token_hex(3).upper()
        c.execute("INSERT INTO drivers(user_id,service,vehicle_label,plate,license_no,status,joined_code) VALUES(?,?,?,?,?,'offline',?)",(uid,service,vehicle,plate,license_no,code))
        c.commit(); audit('partner_created','user',uid,f'service={service};username={username}',current_user()['id'])
    except sqlite3.IntegrityError:
        c.rollback(); c.close(); return redirect(url_for('admin',msg='That username or phone is already in use.'))
    c.close(); return redirect(url_for('admin',msg=f'{SERVICES[service]} partner created.'))

@app.route('/promise212324/driver/<int:uid>/action',methods=['POST'])
@admin_required
def admin_driver_action(uid):
    action=request.form.get('action'); c=get_db();
    if action=='verify': c.execute("UPDATE users SET verified=1 WHERE id=? AND role='driver'",(uid,))
    elif action=='deactivate': c.execute("UPDATE users SET active=0 WHERE id=?",(uid,)); c.execute("UPDATE drivers SET status='offline',deactivated_reason=? WHERE user_id=?",(request.form.get('reason','admin action'),uid))
    elif action=='reactivate': c.execute('UPDATE users SET active=1 WHERE id=?',(uid,))
    c.commit(); c.close(); audit('driver_'+action,'user',uid,actor_id=current_user()['id']); return redirect(url_for('admin'))

@app.route('/promise212324/user/<int:uid>/action',methods=['POST'])
@admin_required
def admin_user_action(uid):
    action=request.form.get('action'); c=get_db(); u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if not u or u['role']=='admin': c.close(); return abort(404)
    if action=='deactivate': c.execute('UPDATE users SET active=0 WHERE id=?',(uid,));
    elif action=='reactivate': c.execute('UPDATE users SET active=1 WHERE id=?',(uid,))
    c.commit(); c.close(); audit('user_'+action,'user',uid,actor_id=current_user()['id']); return redirect(url_for('admin'))

@app.route('/promise212324/complaint/<int:cid>',methods=['POST'])
@admin_required
def admin_complaint(cid):
    c=get_db(); c.execute("UPDATE complaints SET status='resolved',admin_note=?,resolved_at=? WHERE id=?",(request.form.get('note',''),now(),cid)); c.commit(); c.close(); audit('complaint_resolved','complaint',cid,actor_id=current_user()['id']); return redirect(url_for('admin'))

@app.route('/promise212324/settings',methods=['POST'])
@admin_required
def admin_settings():
    keys=['bike_base','bike_per_km','ride_base','ride_per_km','mover_base','mover_per_km','mover_item_fee','mover_helper_fee','platform_commission','otravel_url']
    c=get_db();
    for k in keys:
        if k in request.form: c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,request.form[k].strip()))
    c.commit(); c.close(); audit('settings_updated','settings',actor_id=current_user()['id']); return redirect(url_for('admin'))

@app.route('/promise212324/error/<int:eid>/resolve',methods=['POST'])
@admin_required
def admin_error_resolve(eid):
    c=get_db(); c.execute('UPDATE app_errors SET resolved=1 WHERE id=?',(eid,)); c.commit(); c.close(); audit('error_resolved','app_error',eid,actor_id=current_user()['id']); return redirect(url_for('admin'))

@app.route('/promise212324/backup')
@admin_required
def admin_backup():
    ts=datetime.now().strftime('%Y%m%d-%H%M%S'); dest=BACKUP_DIR/f'o-{ts}.sqlite3'; src=get_db();
    dst=sqlite3.connect(dest); src.backup(dst); dst.close(); src.close(); audit('backup_created','backup',details=str(dest.name),actor_id=current_user()['id']); return send_file(dest,as_attachment=True,download_name=dest.name)

@app.route('/promise212324/export')
@admin_required
def admin_export():
    c=get_db(); payload={}
    for t in ['users','drivers','requests','ratings','complaints','notifications','audits','settings','visitors']:
        payload[t]=[dict(r) for r in c.execute(f'SELECT * FROM {t}').fetchall()]
    c.close(); p=BACKUP_DIR/f'export-{datetime.now().strftime("%Y%m%d-%H%M%S")}.json'; p.write_text(json.dumps(payload,default=str,indent=2)); return send_file(p,as_attachment=True,download_name=p.name)

@app.route('/logout-all')
def noop(): return redirect(url_for('home'))

if __name__=='__main__': app.run(debug=True)
