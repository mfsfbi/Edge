import os, sqlite3, math, json, urllib.parse, urllib.request, secrets, re
from functools import wraps
from datetime import datetime, timezone
from flask import Flask, g, render_template, request, redirect, url_for, session, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode

app = Flask(__name__, template_folder='app/templates', static_folder='app/static')
ADMIN_PATH = '/promise212324'
ADMIN_USER = os.environ.get('USER_NAME', 'admin')
ADMIN_PASS = os.environ.get('PASSWORD', 'change-me')
app.secret_key = generate_password_hash(ADMIN_USER + '|' + ADMIN_PASS)[:64]

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = '/var/data' if os.path.isdir('/var/data') and os.access('/var/data', os.W_OK) else os.path.join(BASE, 'instance')
os.makedirs(DATA, exist_ok=True)
DB = os.path.join(DATA, 'o_system_v1.db')

SERVICES = {'ride': 'O-Ride', 'drive': 'O-Drive', 'mover': 'O-Movers'}
SERVICE_PATHS = {'ride': '/O-Ride', 'drive': '/O-Drive', 'mover': '/O-Movers'}
THEMES = {'light', 'cream', 'mint', 'sky'}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS accounts(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 username TEXT UNIQUE NOT NULL,
 password_hash TEXT NOT NULL,
 role TEXT NOT NULL,
 service TEXT,
 phone TEXT,
 theme TEXT NOT NULL DEFAULT 'light',
 created_at TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS partners(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 account_id INTEGER UNIQUE NOT NULL,
 service TEXT NOT NULL,
 vehicle TEXT,
 plate TEXT,
 licence TEXT,
 rating REAL NOT NULL DEFAULT 5.0,
 completed INTEGER NOT NULL DEFAULT 0,
 earnings REAL NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'offline',
 lat REAL, lon REAL,
 speed_kmh REAL NOT NULL DEFAULT 0,
 item_count INTEGER NOT NULL DEFAULT 0,
 helper_count INTEGER NOT NULL DEFAULT 0,
 last_seen TEXT,
 FOREIGN KEY(account_id) REFERENCES accounts(id)
);
CREATE TABLE IF NOT EXISTS requests(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 customer_id INTEGER,
 guest_name TEXT,
 service TEXT NOT NULL,
 pickup_name TEXT,
 destination_name TEXT,
 pickup_lat REAL,
 pickup_lon REAL,
 dest_lat REAL,
 dest_lon REAL,
 fare REAL,
 payment TEXT,
 status TEXT NOT NULL DEFAULT 'requested',
 partner_id INTEGER,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 item_count INTEGER NOT NULL DEFAULT 0,
 helper_count INTEGER NOT NULL DEFAULT 0,
 FOREIGN KEY(customer_id) REFERENCES accounts(id),
 FOREIGN KEY(partner_id) REFERENCES partners(id)
);
CREATE TABLE IF NOT EXISTS ratings(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 customer_id INTEGER,
 partner_id INTEGER,
 request_id INTEGER,
 app_rating INTEGER,
 partner_rating INTEGER,
 note TEXT,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 customer_id INTEGER,
 guest_name TEXT,
 kind TEXT NOT NULL,
 message TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'open',
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 customer_id INTEGER,
 role TEXT,
 page TEXT,
 service TEXT,
 device TEXT,
 device_model TEXT,
 browser TEXT,
 lat REAL, lon REAL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS system_errors(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 source TEXT NOT NULL,
 route TEXT,
 code INTEGER,
 method TEXT,
 message TEXT,
 status TEXT NOT NULL DEFAULT 'open',
 created_at TEXT NOT NULL
);
'''


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB, timeout=30, isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.executescript(SCHEMA)
        cols = {r['name'] for r in g.db.execute('PRAGMA table_info(events)').fetchall()}
        if 'device_model' not in cols:
            g.db.execute("ALTER TABLE events ADD COLUMN device_model TEXT")
        if 'browser' not in cols:
            g.db.execute("ALTER TABLE events ADD COLUMN browser TEXT")
        if 'lat' not in cols:
            g.db.execute("ALTER TABLE events ADD COLUMN lat REAL")
        if 'lon' not in cols:
            g.db.execute("ALTER TABLE events ADD COLUMN lon REAL")
        pcols = {r['name'] for r in g.db.execute('PRAGMA table_info(partners)').fetchall()}
        if 'speed_kmh' not in pcols:
            g.db.execute("ALTER TABLE partners ADD COLUMN speed_kmh REAL NOT NULL DEFAULT 0")
        if 'item_count' not in pcols:
            g.db.execute("ALTER TABLE partners ADD COLUMN item_count INTEGER NOT NULL DEFAULT 0")
        if 'helper_count' not in pcols:
            g.db.execute("ALTER TABLE partners ADD COLUMN helper_count INTEGER NOT NULL DEFAULT 0")
        rcols = {r['name'] for r in g.db.execute('PRAGMA table_info(requests)').fetchall()}
        if 'item_count' not in rcols:
            g.db.execute("ALTER TABLE requests ADD COLUMN item_count INTEGER NOT NULL DEFAULT 0")
        if 'helper_count' not in rcols:
            g.db.execute("ALTER TABLE requests ADD COLUMN helper_count INTEGER NOT NULL DEFAULT 0")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    conn = g.pop('db', None)
    if conn:
        conn.close()


def now():
    return datetime.now(timezone.utc).isoformat()


def q(sql, args=(), one=False):
    cur = db().execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def actor():
    aid = session.get('account_id')
    return q('SELECT * FROM accounts WHERE id=? AND active=1', (aid,), True) if aid else None


def nav(role='customer', service=None):
    if role == 'admin':
        return '''<nav>
        <a class="navbtn active" href="/promise212324">Overview</a>
        <details class="navgroup" open><summary>O Services</summary>
          <a class="navsub" href="/promise212324/service/ride">O-Ride</a>
          <a class="navsub" href="/promise212324/service/drive">O-Drive</a>
          <a class="navsub" href="/promise212324/service/mover">O-Movers</a>
        </details>
        <details class="navgroup"><summary>Operations</summary>
          <a class="navsub" href="/promise212324/requests">All requests</a>
          <a class="navsub" href="/promise212324/inbox">Inbox</a>
          <a class="navsub" href="/promise212324/complaints">Complaints</a>
          <a class="navsub" href="/promise212324/ratings">Ratings</a>
        </details>
        <details class="navgroup"><summary>People & access</summary>
          <a class="navsub" href="/promise212324/partners">Partners</a>
          <a class="navsub" href="/promise212324/people">People & devices</a>
          <a class="navsub" href="/promise212324/customers">Customers</a>
        </details>
        <details class="navgroup"><summary>System</summary>
          <a class="navsub" href="/promise212324/simulate">Simulation</a>
          <a class="navsub" href="/promise212324/fare-controls">Fare controls</a>
          <a class="navsub" href="/promise212324/backup">Backup</a>
          <a class="navsub" href="/promise212324/export">Export</a>
          <a class="navsub" href="/promise212324/system">System errors</a>
        </details>
        <a class="navbtn" href="/promise212324/logout">Sign out</a></nav>'''
    if role == 'partner':
        return f'''<nav>
        <a class="navbtn active" href="{SERVICE_PATHS.get(service, '/')}">{SERVICES.get(service, 'Partner')} Dashboard</a>
        <a class="navbtn" href="/partner/requests">Requests</a>
        <a class="navbtn" href="/partner/earnings">Earnings</a>
        <a class="navbtn" href="/partner/ratings">Ratings</a>
        <a class="navbtn" href="/partner/help">Help</a>
        <a class="navbtn" href="/logout">Sign out</a></nav>'''
    if session.get('account_id'):
        return '''<nav>
        <a class="navbtn active" href="/services">Services</a>
        <a class="navbtn" href="/customer/trips">My trips</a>
        <a class="navbtn" href="/customer/ratings">Ratings & feedback</a>
        <a class="navbtn" href="/help">Help, concern or request</a>
        <a class="navbtn" href="/qr">O QR</a>
        <a class="navbtn" href="/account">My account</a>
        <a class="navbtn" href="/settings">Appearance</a>
        <a class="navbtn" href="/logout">Sign out</a></nav>'''
    return '''<nav>
    <a class="navbtn active" href="/services">Services</a>
    <a class="navbtn" href="/help">Help, concern or request</a>
    <a class="navbtn" href="/qr">O QR</a>
    <a class="navbtn" href="/login">Sign in</a>
    <a class="navbtn" href="/account/register">Create account</a></nav>'''


def log_event(page, service=None, device=None, model=None, browser=None, lat=None, lon=None):
    a = actor()
    try:
        db().execute(
            'INSERT INTO events(customer_id,role,page,service,device,device_model,browser,lat,lon,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (a['id'] if a else None, a['role'] if a else 'guest', page, service, device, model, browser, lat, lon, now())
        )
    except Exception:
        pass


def add_error(source, route, code, method, message):
    try:
        db().execute('INSERT INTO system_errors(source,route,code,method,message,created_at) VALUES(?,?,?,?,?,?)',
                     (source, route, code, method, message[:500], now()))
    except Exception:
        pass


def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            a = actor()
            if not a:
                return redirect(url_for('login', next=request.path))
            if role and a['role'] != role:
                abort(403)
            return fn(*args, **kwargs)
        return inner
    return deco


def admin_required(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('admin_login', next=request.path))
        return fn(*args, **kwargs)
    return inner


@app.before_request
def before():
    db()
    db().execute("INSERT OR IGNORE INTO settings(key,value) VALUES('simulate','0')")
    defaults={'ride_base':'55','ride_km':'18','ride_min':'60','drive_base':'110','drive_km':'42','drive_min':'150','mover_base':'600','mover_km':'60','mover_min':'700','mover_item':'100','mover_helper':'650','commission':'10'}
    for k,v in defaults.items(): db().execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',(k,v))


@app.get('/health')
def health():
    return jsonify(ok=True, version='O-System V1 Dispatch')


@app.get('/')
def home():
    log_event('home')
    return render_template('home.html', sidebar=nav(), page_theme='dark')


@app.get('/services')
def services():
    a = actor(); log_event('services', device=None)
    return render_template('services.html', sidebar=nav(), page_theme=(a['theme'] if a else 'light'))


@app.get('/qr')
def qr_page():
    log_event('qr')
    return render_template('qr.html', sidebar=nav(), page_theme='light')


@app.get('/qr-image.svg')
def qr_image():
    target = request.url_root.rstrip('/') + '/'
    qr = qrcode.QRCode(border=4, box_size=8)
    qr.add_data(target); qr.make(fit=True)
    matrix = qr.get_matrix(); n = len(matrix)
    rects = ''.join(f'<rect x="{x}" y="{y}" width="1" height="1"/>' for y,row in enumerate(matrix) for x,dark in enumerate(row) if dark)
    svg = f'<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="white"/><g fill="#111827">{rects}</g></svg>'
    resp = app.response_class(svg, mimetype='image/svg+xml'); resp.headers['Cache-Control']='no-store'; return resp


@app.get('/qr-image.png')
def qr_image_png_compat():
    return qr_image()


@app.get('/sw.js')
def root_service_worker():
    return app.send_static_file('sw.js')


@app.post('/api/visitor/context')
def visitor_context():
    data = request.get_json(silent=True) or {}
    log_event(data.get('page', request.referrer or '/')[:120], data.get('service'), data.get('device'), data.get('device_model'), data.get('browser'), data.get('lat'), data.get('lon'))
    return jsonify(ok=True)


@app.route('/account/register', methods=['GET','POST'])
def register():
    err=''
    if request.method=='POST':
        name=request.form.get('name','').strip(); username=request.form.get('username','').strip().lower(); phone=request.form.get('phone','').strip(); pw=request.form.get('password','')
        if not name or not username or len(pw)<6: err='Enter your name, username and a password of at least 6 characters.'
        elif q('SELECT id FROM accounts WHERE username=?',(username,),True): err='That username is already in use.'
        else:
            cur=db().execute('INSERT INTO accounts(name,username,password_hash,role,phone,created_at) VALUES(?,?,?,?,?,?)',(name,username,generate_password_hash(pw),'customer',phone,now()))
            session['account_id']=cur.lastrowid
            return redirect(url_for('services'))
    return render_template('register.html', sidebar=nav(), error=err, page_theme='light')


@app.route('/login', methods=['GET','POST'])
def login():
    err=''; next_url=request.args.get('next','/services')
    if request.method=='POST':
        identifier=request.form.get('username','').strip().lower(); pw=request.form.get('password','')
        a=q('SELECT * FROM accounts WHERE active=1 AND (lower(username)=? OR lower(name)=? OR replace(phone," ","")=?) ORDER BY id LIMIT 1',(identifier,identifier,identifier.replace(' ','')),True)
        if a and check_password_hash(a['password_hash'],pw):
            session['account_id']=a['id']
            return redirect(SERVICE_PATHS.get(a['service'],'/services') if a['role']=='partner' else (next_url if next_url.startswith('/') else '/services'))
        err='The name/username or password is not correct.'
    return render_template('login.html',sidebar=nav(),error=err,page_theme='light')


@app.get('/logout')
def logout(): session.clear(); return redirect(url_for('home'))


@app.route('/settings', methods=['GET','POST'])
@login_required('customer')
def settings():
    a=actor(); msg=None; err=None
    if request.method=='POST':
        theme=request.form.get('theme','light')
        if theme not in THEMES: err='Choose a valid appearance.'
        else: db().execute('UPDATE accounts SET theme=? WHERE id=?',(theme,a['id'])); msg='Appearance updated.'; a=actor()
    return render_template('settings.html',sidebar=nav(),account=a,error=err,success=msg,page_theme=a['theme'])


@app.route('/account', methods=['GET','POST'])
@login_required('customer')
def account_page():
    a=actor(); msg=None; err=None
    if request.method=='POST':
        name=request.form.get('name','').strip(); phone=request.form.get('phone','').strip()
        if not name: err='Name is required.'
        else: db().execute('UPDATE accounts SET name=?,phone=? WHERE id=?',(name,phone,a['id'])); msg='Account updated.'; a=actor()
    return render_template('account.html',sidebar=nav(),account=a,error=err,success=msg,page_theme=a['theme'])


@app.post('/api/app-rating')
@login_required('customer')
def app_rating():
    data=request.get_json(silent=True) or request.form; value=int(data.get('rating',0) or 0); note=(data.get('note') or '').strip()
    if value not in (1,2,3,4,5): return jsonify(ok=False,error='Choose a rating from 1 to 5.'),400
    db().execute('INSERT INTO ratings(customer_id,app_rating,note,created_at) VALUES(?,?,?,?)',(actor()['id'],value,note,now())); return jsonify(ok=True)


@app.get('/customer/trips')
@login_required('customer')
def trips():
    rows=q('SELECT r.*,p.id pid,a.name partner_name FROM requests r LEFT JOIN partners p ON p.id=r.partner_id LEFT JOIN accounts a ON a.id=p.account_id WHERE r.customer_id=? ORDER BY r.id DESC LIMIT 50',(actor()['id'],))
    return render_template('trips.html',sidebar=nav(),trips=rows,page_theme=actor()['theme'])


@app.get('/customer/ratings')
@login_required('customer')
def ratings_page():
    a=actor(); rows=q('SELECT x.*,r.destination_name,a.name partner_name FROM ratings x LEFT JOIN requests r ON r.id=x.request_id LEFT JOIN partners p ON p.id=x.partner_id LEFT JOIN accounts a ON a.id=p.account_id WHERE x.customer_id=? ORDER BY x.id DESC',(a['id'],))
    completed=q("SELECT r.*,a.name partner_name,p.id partner_id FROM requests r LEFT JOIN partners p ON p.id=r.partner_id LEFT JOIN accounts a ON a.id=p.account_id WHERE r.customer_id=? AND r.status='completed' ORDER BY r.id DESC",(a['id'],))
    return render_template('ratings.html',sidebar=nav(),ratings=rows,completed=completed,page_theme=a['theme'])


@app.post('/api/rate')
@login_required('customer')
def rate():
    data=request.get_json(silent=True) or request.form; rid=int(data.get('request_id')); appv=int(data.get('app_rating',0) or 0); pr=int(data.get('partner_rating',0) or 0); note=(data.get('note') or '').strip()
    r=q("SELECT * FROM requests WHERE id=? AND customer_id=? AND status='completed'",(rid,actor()['id']),True)
    if not r: return jsonify(ok=False,error='Trip not found'),404
    db().execute('INSERT INTO ratings(customer_id,partner_id,request_id,app_rating,partner_rating,note,created_at) VALUES(?,?,?,?,?,?,?)',(actor()['id'],r['partner_id'],rid,appv or None,pr or None,note,now()))
    if pr and r['partner_id']:
        db().execute('UPDATE partners SET rating=(SELECT ROUND(AVG(partner_rating),1) FROM ratings WHERE partner_id=? AND partner_rating IS NOT NULL) WHERE id=?',(r['partner_id'],r['partner_id']))
    return jsonify(ok=True)


@app.route('/help', methods=['GET','POST'])
def help_page():
    err=''; success=None
    if request.method=='POST':
        a=actor(); kind=request.form.get('kind','concern'); msg=request.form.get('message','').strip(); guest=request.form.get('guest_name','').strip()
        if not msg: err='Please tell us what you need.'
        else:
            db().execute('INSERT INTO feedback(customer_id,guest_name,kind,message,created_at) VALUES(?,?,?,?,?)',(a['id'] if a else None,guest,kind,msg,now())); success='Your message has been sent to O.'
    return render_template('help.html',sidebar=nav(),error=err,success=success,page_theme=(actor()['theme'] if actor() else 'light'))


@app.get('/service/<service>')
def customer_service(service):
    if service not in SERVICES: abort(404)
    a=actor(); log_event('service',service)
    return render_template('service.html',sidebar=nav(),service=service,service_name=SERVICES[service],page_theme=(a['theme'] if a else 'light'))


@app.route('/O-Ride')
@app.route('/O-Drive')
@app.route('/O-Movers')
def provider_entry():
    path=request.path.lower()
    service='ride' if 'ride' in path else 'drive' if 'drive' in path else 'mover'
    a=actor()
    if a and a['role']=='partner':
        # Never strand a valid partner on an access-denied page: send them to
        # the dashboard belonging to the service on their account.
        actual=a['service'] if a['service'] in SERVICES else service
        return redirect(url_for('partner_home',service=actual))
    return render_template('provider_entry.html',service=service,service_name=SERVICES[service],action='/provider-login',page_theme='light')


@app.post('/provider-login')
def provider_login_post():
    service=request.form.get('service')
    identifier=request.form.get('username','').strip().lower()
    pw=request.form.get('password','')
    a=q("SELECT * FROM accounts WHERE lower(username)=? AND active=1 AND role='partner'",(identifier,),True)
    if a and a['service'] in SERVICES and check_password_hash(a['password_hash'],pw):
        session['account_id']=a['id']
        return redirect(url_for('partner_home',service=a['service']))
    return render_template('provider_entry.html',service=service,service_name=SERVICES.get(service,service),action='/provider-login',error='Jina la mtumiaji au nenosiri si sahihi.',page_theme='light')


@app.get('/partner/<service>')
@login_required('partner')
def partner_home(service):
    a=actor()
    p=q('SELECT p.*,a.name,a.phone,a.username FROM partners p JOIN accounts a ON a.id=p.account_id WHERE p.account_id=?',(a['id'],),True)
    if not p or p['service'] not in SERVICES:
        return redirect('/logout')
    # A partner can only enter their own service workspace. Redirect rather than 403.
    if p['service']!=service:
        return redirect(url_for('partner_home',service=p['service']))
    reqs=q("SELECT r.*,COALESCE(a.name,r.guest_name,'Guest') customer_name,COALESCE(a.phone,'') customer_phone FROM requests r LEFT JOIN accounts a ON a.id=r.customer_id WHERE r.service=? AND (r.partner_id=? OR (r.partner_id IS NULL AND r.status='requested')) ORDER BY CASE WHEN r.partner_id=? THEN 0 ELSE 1 END, r.id DESC LIMIT 50",(service,p['id'],p['id']))
    friends=q('SELECT p.*,a.name,a.phone FROM partners p JOIN accounts a ON a.id=p.account_id WHERE p.service=? AND a.active=1 AND p.id!=? AND p.lat IS NOT NULL AND p.lon IS NOT NULL',(service,p['id']))
    return render_template('partner.html',sidebar=nav('partner',service),partner=p,requests=reqs,friends=friends,service=service,service_name=SERVICES[service],page_theme='light')


@app.post('/api/partner/status')
@login_required('partner')
def partner_status():
    a=actor(); p=q('SELECT * FROM partners WHERE account_id=?',(a['id'],),True); data=request.get_json() or {}
    status=data.get('status','orange')
    if status not in ('offline','orange','green','blue'): status='orange'
    lat=data.get('lat'); lon=data.get('lon')
    speed=0.0
    try:
        if lat is not None and lon is not None and p['lat'] is not None and p['lon'] is not None and p['last_seen']:
            t0=datetime.fromisoformat(p['last_seen']); dt=max((datetime.now(timezone.utc)-t0).total_seconds()/3600,0.001)
            km=math.hypot((float(lat)-p['lat'])*111,(float(lon)-p['lon'])*111*math.cos(math.radians(float(lat))))
            speed=min(km/dt,160)
    except Exception:
        speed=0.0
    db().execute('UPDATE partners SET status=?,lat=?,lon=?,speed_kmh=?,last_seen=? WHERE id=?',(status,lat,lon,speed,now(),p['id']))
    return jsonify(ok=True,status=status,speed_kmh=round(speed,1))


@app.post('/api/partner/request')
@login_required('partner')
def partner_request():
    a=actor(); p=q('SELECT * FROM partners WHERE account_id=?',(a['id'],),True); data=request.get_json() or {}; rid=int(data.get('request_id')); act=data.get('action')
    r=q('SELECT * FROM requests WHERE id=? AND service=?',(rid,p['service']),True)
    if not r: return jsonify(ok=False,error='Request not found'),404
    if act=='decline' and r['status'] in ('requested','assigned') and (r['partner_id'] in (None,p['id'])):
        if r['partner_id']==p['id']: db().execute("UPDATE requests SET partner_id=NULL,status='requested',updated_at=? WHERE id=?",(now(),rid)); db().execute("UPDATE partners SET status='orange' WHERE id=?",(p['id'],))
    elif act=='accept' and r['status']=='requested':
        conn=db(); conn.execute('BEGIN IMMEDIATE')
        changed=conn.execute("UPDATE requests SET partner_id=?,status='assigned',updated_at=? WHERE id=? AND partner_id IS NULL AND status='requested' AND EXISTS (SELECT 1 FROM partners px WHERE px.id=? AND px.status='orange')",(p['id'],now(),rid,p['id'])).rowcount
        if changed: conn.execute("UPDATE partners SET status='green' WHERE id=?",(p['id'],))
        conn.execute('COMMIT')
        if not changed: return jsonify(ok=False,error='Another partner has already taken this customer, or you are not available.'),409
    elif act=='start' and r['partner_id']==p['id']:
        db().execute("UPDATE requests SET status='on_trip',updated_at=? WHERE id=?",(now(),rid)); db().execute("UPDATE partners SET status='blue' WHERE id=?",(p['id'],))
    elif act=='complete' and r['partner_id']==p['id']:
        db().execute("UPDATE requests SET status='completed',updated_at=? WHERE id=?",(now(),rid)); db().execute("UPDATE partners SET status='orange',completed=completed+1,earnings=earnings+COALESCE(?,0) WHERE id=?",(r['fare'],p['id']))
    return jsonify(ok=True)


@app.get('/api/partner/live')
@login_required('partner')
def partner_live():
    a=actor(); p=q('SELECT p.*,a.name,a.phone,a.username FROM partners p JOIN accounts a ON a.id=p.account_id WHERE p.account_id=?',(a['id'],),True)
    if not p: return jsonify(ok=False),404
    service=p['service']
    rows=q("SELECT r.*,COALESCE(a.name,r.guest_name,'Guest') customer_name,COALESCE(a.phone,'') customer_phone,r.pickup_lat customer_lat,r.pickup_lon customer_lon FROM requests r LEFT JOIN accounts a ON a.id=r.customer_id WHERE r.service=? AND (r.status='requested' OR (r.partner_id=? AND r.status IN ('assigned','on_trip'))) ORDER BY CASE WHEN r.partner_id=? THEN 0 ELSE 1 END, r.id DESC",(service,p['id'],p['id']))
    friends=q("SELECT p.id,p.service,p.status,p.lat,p.lon,p.speed_kmh,p.rating,a.name,a.phone FROM partners p JOIN accounts a ON a.id=p.account_id WHERE p.service=? AND a.active=1 AND p.lat IS NOT NULL AND p.lon IS NOT NULL ORDER BY p.id",(service,))
    result=[]
    for r in rows:
        z=dict(r); z['distance_km']=None
        if r['customer_lat'] is not None and p['lat'] is not None:
            z['distance_km']=round(math.hypot((r['customer_lat']-p['lat'])*111,(r['customer_lon']-p['lon'])*111*math.cos(math.radians(float(p['lat'])))),2)
        result.append(z)
    result.sort(key=lambda z:(0 if z['partner_id']==p['id'] else 1, z['distance_km'] if z['distance_km'] is not None else 9999, z['id']))
    return jsonify(ok=True,partner=dict(p),requests=result,friends=[dict(x) for x in friends])


@app.get('/api/partner/dashboard')
@login_required('partner')
def partner_dashboard_api():
    a=actor(); p=q('SELECT p.*,a.name,a.phone,a.username FROM partners p JOIN accounts a ON a.id=p.account_id WHERE p.account_id=?',(a['id'],),True)
    if not p: return jsonify(ok=False),404
    rows=q("SELECT r.id,r.customer_id,r.guest_name,r.pickup_name,r.destination_name,r.fare,r.payment,r.status,r.created_at,COALESCE(a.name,r.guest_name,'Guest') customer_name,COALESCE(a.phone,'') customer_phone FROM requests r LEFT JOIN accounts a ON a.id=r.customer_id WHERE r.service=? AND (r.partner_id=? OR (r.partner_id IS NULL AND r.status='requested')) ORDER BY r.id DESC LIMIT 50",(p['service'],p['id']))
    return jsonify(ok=True,partner=dict(p),requests=[dict(r) for r in rows])

@app.get('/partner/requests')
@login_required('partner')
def partner_requests(): return redirect(url_for('partner_home',service=actor()['service']))

@app.get('/partner/earnings')
@login_required('partner')
def partner_earnings():
    a=actor(); p=q('SELECT * FROM partners WHERE account_id=?',(a['id'],),True)
    return render_template('partner_info.html',sidebar=nav('partner',p['service']),heading='Earnings',partner=p,message=f"KES {p['earnings']:.0f} recorded on completed trips.",page_theme='light')

@app.get('/partner/ratings')
@login_required('partner')
def partner_ratings():
    a=actor(); p=q('SELECT * FROM partners WHERE account_id=?',(a['id'],),True); rows=q('SELECT x.*,a.name customer_name FROM ratings x LEFT JOIN accounts a ON a.id=x.customer_id WHERE x.partner_id=? ORDER BY x.id DESC',(p['id'],))
    return render_template('partner_ratings.html',sidebar=nav('partner',p['service']),partner=p,rows=rows,page_theme='light')

@app.get('/partner/help')
@login_required('partner')
def partner_help(): return redirect(url_for('help_page'))


@app.get('/api/partners/map')
def partners_map():
    service=request.args.get('service')
    args=[]; where='a.active=1 AND p.lat IS NOT NULL AND p.lon IS NOT NULL'
    if service in SERVICES: where += ' AND p.service=?'; args.append(service)
    rows=q(f'SELECT p.id,p.service,p.status,p.lat,p.lon,p.speed_kmh,a.name,a.phone FROM partners p JOIN accounts a ON a.id=p.account_id WHERE {where}',args)
    return jsonify(partners=[dict(r) for r in rows])


@app.get('/api/partners/nearby')
def nearby_partners():
    service=request.args.get('service'); lat=float(request.args.get('lat','0')); lon=float(request.args.get('lon','0'))
    rows=q("SELECT p.*,a.name FROM partners p JOIN accounts a ON a.id=p.account_id WHERE p.service=? AND a.active=1 AND p.status='orange' AND p.lat IS NOT NULL AND p.lon IS NOT NULL",(service,))
    out=[]
    for p in rows:
        d=math.hypot((p['lat']-lat)*111,(p['lon']-lon)*111*math.cos(math.radians(lat)))
        out.append({'id':p['id'],'name':p['name'],'lat':p['lat'],'lon':p['lon'],'distance_km':round(d,2),'rating':p['rating'],'speed_kmh':p['speed_kmh']})
    return jsonify(sorted(out,key=lambda x:(x['distance_km'],x['id']))[:12])


@app.get('/api/request/<int:rid>')
def request_status(rid):
    r=q('SELECT r.*,p.lat partner_lat,p.lon partner_lon,p.status partner_status,p.speed_kmh partner_speed,p.rating partner_rating,p.vehicle partner_vehicle,p.plate partner_plate,a.name partner_name,a.phone partner_phone FROM requests r LEFT JOIN partners p ON p.id=r.partner_id LEFT JOIN accounts a ON a.id=p.account_id WHERE r.id=?',(rid,),True)
    if not r: return jsonify(ok=False),404
    a=actor()
    if not session.get('admin') and (not a or (a['role']=='customer' and r['customer_id']!=a['id']) or (a['role']=='partner' and r['service']!=a['service'])): return jsonify(ok=False),403
    return jsonify(dict(r))



@app.get('/api/partner/<int:pid>/profile')
def partner_profile(pid):
    p=q("SELECT p.*,a.name,a.phone,a.username FROM partners p JOIN accounts a ON a.id=p.account_id WHERE p.id=? AND a.active=1",(pid,),True)
    if not p: return jsonify(ok=False,error='Partner not found'),404
    reviews=q("SELECT r.partner_rating,r.note,r.created_at,c.name customer_name FROM ratings r LEFT JOIN accounts c ON c.id=r.customer_id WHERE r.partner_id=? AND r.partner_rating IS NOT NULL ORDER BY r.id DESC LIMIT 8",(pid,))
    avg=p['rating'] or 0
    return jsonify(ok=True,partner={
        'id':p['id'],'name':p['name'],'service':p['service'],'phone':p['phone'],'rating':round(float(avg),1),
        'completed':p['completed'],'vehicle':p['vehicle'],'plate':p['plate'],'status':p['status'],
        'reviews':[{'rating':r['partner_rating'],'note':r['note'] or '', 'name':r['customer_name'] or 'Customer','date':r['created_at']} for r in reviews]
    })

@app.get('/api/admin/live-map')
@admin_required
def admin_live_map():
    partners=[dict(r) for r in q('SELECT p.id,p.service,p.status,p.lat,p.lon,p.speed_kmh,a.name,a.phone FROM partners p JOIN accounts a ON a.id=p.account_id WHERE a.active=1')]
    requests=[dict(r) for r in q("SELECT r.*,COALESCE(a.name,r.guest_name,'Guest') customer_name,p.status partner_status FROM requests r LEFT JOIN accounts a ON a.id=r.customer_id LEFT JOIN partners p ON p.id=r.partner_id WHERE r.status IN ('requested','assigned','on_trip') ORDER BY r.id DESC LIMIT 100")]
    visitors=[dict(r) for r in q("SELECT display_name,role,page,service,lat,lon,created_at FROM (SELECT COALESCE(a.name,e.role,'Guest') display_name,e.role,e.page,e.service,e.lat,e.lon,e.created_at,e.id,e.customer_id,ROW_NUMBER() OVER (PARTITION BY COALESCE(e.customer_id,'guest-'||e.id) ORDER BY e.id DESC) rn FROM events e LEFT JOIN accounts a ON a.id=e.customer_id WHERE e.lat IS NOT NULL AND e.lon IS NOT NULL) WHERE rn=1 ORDER BY created_at DESC LIMIT 120")]
    return jsonify(partners=partners,requests=requests,visitors=visitors)


@app.get('/api/geocode/search')
def geocode_search():
    qv=request.args.get('q','').strip()
    if not qv: return jsonify([])
    try:
        url='https://nominatim.openstreetmap.org/search?'+urllib.parse.urlencode({'q':qv+', Kenya','format':'json','limit':5})
        req=urllib.request.Request(url,headers={'User-Agent':'O-System-V1/1.0'})
        with urllib.request.urlopen(req,timeout=8) as r: data=json.load(r)
        return jsonify([{'name':x.get('display_name',''),'lat':float(x['lat']),'lon':float(x['lon'])} for x in data])
    except Exception as e:
        add_error('server','/api/geocode/search',503,'GET',str(e)); return jsonify([])


@app.get('/api/route')
def route_api():
    try:
        a=(float(request.args['olat']),float(request.args['olon'])); b=(float(request.args['dlat']),float(request.args['dlon']))
        coords=f'{a[1]},{a[0]};{b[1]},{b[0]}'
        url='https://router.project-osrm.org/route/v1/driving/'+coords+'?overview=full&geometries=geojson'
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'O-System-V1/1.0'}),timeout=12) as r: data=json.load(r)
        rt=data['routes'][0]
        return jsonify(distance_km=rt['distance']/1000,duration_min=rt['duration']/60,geometry=[[p[1],p[0]] for p in rt['geometry']['coordinates']])
    except Exception as e:
        add_error('server','/api/route',503,'GET','Road routing unavailable')
        return jsonify(error='road_route_unavailable'),503


def partner_candidates(conn, service, lat, lon):
    rows=conn.execute("SELECT p.*,a.name FROM partners p JOIN accounts a ON a.id=p.account_id WHERE p.service=? AND a.active=1 AND p.status='orange' AND p.lat IS NOT NULL AND p.lon IS NOT NULL",(service,)).fetchall()
    scored=[]
    for p in rows:
        d=math.hypot((p['lat']-lat)*111,(p['lon']-lon)*111*math.cos(math.radians(lat)))
        scored.append((d,p['id'],p))
    scored.sort(key=lambda x:(x[0],x[1]))
    return scored


@app.post('/api/request')
def create_request():
    data=request.get_json() or {}; service=data.get('service')
    if service not in SERVICES: return jsonify(ok=False,error='Invalid service'),400
    pickup=data.get('pickup') or {}; dest=data.get('destination') or {}; a=actor(); guest=data.get('guest_name','').strip()
    if not all(v is not None for v in (pickup.get('lat'),pickup.get('lon'),dest.get('lat'),dest.get('lon'))): return jsonify(ok=False,error='Choose pickup and destination on the map'),400
    dist=float(data.get('distance_km') or 0)
    rates={
        'ride':(float(q("SELECT value FROM settings WHERE key='ride_base'",one=True)['value']),float(q("SELECT value FROM settings WHERE key='ride_km'",one=True)['value']),float(q("SELECT value FROM settings WHERE key='ride_min'",one=True)['value'])),
        'drive':(float(q("SELECT value FROM settings WHERE key='drive_base'",one=True)['value']),float(q("SELECT value FROM settings WHERE key='drive_km'",one=True)['value']),float(q("SELECT value FROM settings WHERE key='drive_min'",one=True)['value'])),
        'mover':(float(q("SELECT value FROM settings WHERE key='mover_base'",one=True)['value']),float(q("SELECT value FROM settings WHERE key='mover_km'",one=True)['value']),float(q("SELECT value FROM settings WHERE key='mover_min'",one=True)['value']))
    }; base,pkm,mn=rates[service]; fare=max(mn,base+dist*pkm)
    if service=='mover': fare += int(data.get('item_count') or 0)*float(q("SELECT value FROM settings WHERE key='mover_item'",one=True)['value']) + int(data.get('helper_count') or 0)*float(q("SELECT value FROM settings WHERE key='mover_helper'",one=True)['value'])
    fare=round(fare/10)*10
    conn=db(); rid=None; best=None
    try:
        conn.execute('BEGIN IMMEDIATE')
        t=now()
        cur=conn.execute('INSERT INTO requests(customer_id,guest_name,service,pickup_name,destination_name,pickup_lat,pickup_lon,dest_lat,dest_lon,fare,payment,status,created_at,updated_at,item_count,helper_count) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(a['id'] if a else None,guest,service,pickup.get('name','Pickup'),dest.get('name','Destination'),pickup['lat'],pickup['lon'],dest['lat'],dest['lon'],fare,data.get('payment','Cash'),'requested',t,t,int(data.get('item_count') or 0),int(data.get('helper_count') or 0)))
        rid=cur.lastrowid
        # Request remains open until an eligible partner accepts it.
        conn.execute('COMMIT')
        scored=partner_candidates(db(),service,float(pickup['lat']),float(pickup['lon']))
        best=scored[0][2] if scored else None
    except Exception:
        try: conn.execute('ROLLBACK')
        except Exception: pass
        add_error('server','/api/request',500,'POST','Could not create request')
        return jsonify(ok=False,error='Unable to create request'),500
    return jsonify(ok=True,id=rid,fare=fare,assigned=best['name'] if best else None,status='assigned' if best else 'requested')


@app.post('/api/request/<int:rid>/cancel')
def cancel_request(rid):
    a=actor(); r=q('SELECT * FROM requests WHERE id=?',(rid,),True)
    if not r or (a and r['customer_id']!=a['id']): return jsonify(ok=False,error='Trip not found'),404
    if r['status'] not in ('requested','assigned'): return jsonify(ok=False,error='Trip can no longer be cancelled'),400
    db().execute("UPDATE requests SET status='cancelled',updated_at=? WHERE id=?",(now(),rid))
    if r['partner_id']: db().execute("UPDATE partners SET status='orange' WHERE id=?",(r['partner_id'],))
    return jsonify(ok=True)

@app.post('/api/pwa/install')
def pwa_install():
    data=request.get_json(silent=True) or {}
    try:
        db().execute("CREATE TABLE IF NOT EXISTS pwa_installs(id INTEGER PRIMARY KEY AUTOINCREMENT,account_id INTEGER,event TEXT,created_at TEXT NOT NULL)")
        a=actor(); db().execute('INSERT INTO pwa_installs(account_id,event,created_at) VALUES(?,?,?)',(a['id'] if a else None,data.get('event','install'),now()))
    except Exception as e:
        add_error('server','/api/pwa/install',500,'POST',str(e))
    return jsonify(ok=True)


# Admin
@app.route(ADMIN_PATH, methods=['GET','POST'])
def admin_login():
    if session.get('admin'):
        def count(sql,args=()): return q(sql,args,True)['c']
        stats={
            'customers':count("SELECT count(*) c FROM accounts WHERE role='customer'"),
            'partners':count("SELECT count(*) c FROM accounts WHERE role='partner'"),
            'open_requests':count("SELECT count(*) c FROM requests WHERE status IN ('requested','assigned','on_trip')"),
            'open_feedback':count("SELECT count(*) c FROM feedback WHERE status='open'"),
            'devices':count("SELECT count(DISTINCT COALESCE(device_model,device)) c FROM events"),
            'ride_partners':count("SELECT count(*) c FROM partners WHERE service='ride' AND status!='offline'"),
            'drive_partners':count("SELECT count(*) c FROM partners WHERE service='drive' AND status!='offline'"),
            'mover_partners':count("SELECT count(*) c FROM partners WHERE service='mover' AND status!='offline'"),
            'ride_open':count("SELECT count(*) c FROM requests WHERE service='ride' AND status IN ('requested','assigned','on_trip')"),
            'drive_open':count("SELECT count(*) c FROM requests WHERE service='drive' AND status IN ('requested','assigned','on_trip')"),
            'mover_open':count("SELECT count(*) c FROM requests WHERE service='mover' AND status IN ('requested','assigned','on_trip')"),
            'people':count("SELECT count(DISTINCT COALESCE(device_model,device)) c FROM events WHERE COALESCE(device_model,device)!=''"),
            'complaints':count("SELECT count(*) c FROM feedback WHERE kind='complaint' AND status='open'"),
            'errors':count("SELECT count(*) c FROM system_errors WHERE status='open'"),
            'ratings':count("SELECT count(*) c FROM ratings"),
            'installs':count("SELECT count(*) c FROM pwa_installs") if q("SELECT name FROM sqlite_master WHERE type='table' AND name='pwa_installs'",one=True) else 0,
            'completed_requests':count("SELECT count(*) c FROM requests WHERE status='completed'"),
            'gross_fares':q("SELECT COALESCE(SUM(fare),0) total FROM requests WHERE status='completed'",one=True)['total'],
            'simulate':q("SELECT value FROM settings WHERE key='simulate'",one=True)['value']=='1',
        }
        return render_template('admin.html',sidebar=nav('admin'),stats=stats,page_theme='light')
    err=''
    if request.method=='POST':
        if request.form.get('username')==ADMIN_USER and request.form.get('password')==ADMIN_PASS:
            session['admin']=True; return redirect(ADMIN_PATH)
        err='Admin credentials are not correct.'
    return render_template('admin_login.html',sidebar='',error=err,page_theme='light')

@app.get('/admin')
def admin_block(): abort(404)

@app.get(ADMIN_PATH+'/logout')
def admin_logout(): session.pop('admin',None); return redirect(url_for('admin_login'))

@app.get(ADMIN_PATH+'/service/<service>')
@admin_required
def admin_service(service):
    if service not in SERVICES: abort(404)
    reqs=q("SELECT r.*,COALESCE(c.name,r.guest_name,'Guest') customer_name,p.id partner_id,pa.name partner_name,p.status partner_status,p.lat partner_lat,p.lon partner_lon,p.speed_kmh FROM requests r LEFT JOIN accounts c ON c.id=r.customer_id LEFT JOIN partners p ON p.id=r.partner_id LEFT JOIN accounts pa ON pa.id=p.account_id WHERE r.service=? ORDER BY r.id DESC LIMIT 80",(service,))
    partners=q("SELECT p.*,a.name,a.username,a.phone,a.active a_active FROM partners p JOIN accounts a ON a.id=p.account_id WHERE p.service=? ORDER BY a.name",(service,))
    return render_template('admin_service.html',sidebar=nav('admin'),service=service,service_name=SERVICES[service],requests=reqs,partners=partners,page_theme='light')

@app.route(ADMIN_PATH+'/partners',methods=['GET','POST'])
@admin_required
def admin_partners():
    if request.method=='POST':
        name=request.form.get('name','').strip(); username=request.form.get('username','').strip().lower(); pw=request.form.get('password',''); service=request.form.get('service')
        if name and username and pw and service in SERVICES and not q('SELECT id FROM accounts WHERE username=?',(username,),True):
            cur=db().execute('INSERT INTO accounts(name,username,password_hash,role,phone,created_at) VALUES(?,?,?,?,?,?)',(name,username,generate_password_hash(pw),'partner',request.form.get('phone',''),now()))
            aid=cur.lastrowid; db().execute("INSERT INTO partners(account_id,service,vehicle,plate,licence,status) VALUES(?,?,?,?,?,'orange')",(aid,service,request.form.get('vehicle',''),request.form.get('plate',''),request.form.get('licence','')))
    partners=q('SELECT p.*,a.name,a.username,a.active,a.phone FROM partners p JOIN accounts a ON a.id=p.account_id ORDER BY p.service,a.name')
    return render_template('admin_partners.html',sidebar=nav('admin'),partners=partners,page_theme='light')

@app.post(ADMIN_PATH+'/partner/<int:pid>/status')
@admin_required
def admin_partner_status(pid):
    p=q('SELECT * FROM partners WHERE id=?',(pid,),True)
    if not p: abort(404)
    status=request.form.get('status','offline')
    if status not in ('offline','orange','green','blue'): status='offline'
    db().execute('UPDATE partners SET status=? WHERE id=?',(status,pid))
    return redirect(request.referrer or url_for('admin_partners'))

@app.post(ADMIN_PATH+'/partner/<int:pid>/toggle')
@admin_required
def toggle_partner(pid):
    p=q('SELECT * FROM partners WHERE id=?',(pid,),True)
    if not p: abort(404)
    a=q('SELECT * FROM accounts WHERE id=?',(p['account_id'],),True); new=0 if a['active'] else 1
    db().execute('UPDATE accounts SET active=? WHERE id=?',(new,a['id'])); db().execute('UPDATE partners SET status=? WHERE id=?',('orange' if new else 'offline',pid)); return redirect(url_for('admin_partners'))

@app.get(ADMIN_PATH+'/people')
@admin_required
def admin_people():
    people=q('''SELECT e.*,COALESCE(a.name,e.role,'Guest') display_name,COALESCE(a.username,'') username,COALESCE(a.phone,'') account_phone FROM events e LEFT JOIN accounts a ON a.id=e.customer_id ORDER BY e.id DESC LIMIT 160''')
    return render_template('admin_people.html',sidebar=nav('admin'),people=people,page_theme='light')

@app.get(ADMIN_PATH+'/inbox')
@admin_required
def admin_inbox():
    rows=q('SELECT f.*,a.name account_name,a.phone account_phone FROM feedback f LEFT JOIN accounts a ON a.id=f.customer_id ORDER BY f.id DESC LIMIT 120')
    return render_template('admin_feedback.html',sidebar=nav('admin'),heading='Inbox',rows=rows,mode='inbox',page_theme='light')

@app.get(ADMIN_PATH+'/complaints')
@admin_required
def admin_complaints():
    rows=q("SELECT f.*,a.name account_name,a.phone account_phone FROM feedback f LEFT JOIN accounts a ON a.id=f.customer_id WHERE f.kind='complaint' ORDER BY f.id DESC LIMIT 120")
    return render_template('admin_feedback.html',sidebar=nav('admin'),heading='Complaints',rows=rows,mode='complaints',page_theme='light')

@app.get(ADMIN_PATH+'/ratings')
@admin_required
def admin_ratings():
    rows=q('SELECT r.*,c.name customer_name,c.phone customer_phone,p.service,a.name partner_name FROM ratings r LEFT JOIN accounts c ON c.id=r.customer_id LEFT JOIN partners p ON p.id=r.partner_id LEFT JOIN accounts a ON a.id=p.account_id ORDER BY r.id DESC LIMIT 160')
    return render_template('admin_feedback.html',sidebar=nav('admin'),heading='Ratings',rows=rows,mode='ratings',page_theme='light')

@app.post(ADMIN_PATH+'/feedback/<int:fid>/close')
@admin_required
def close_feedback(fid): db().execute("UPDATE feedback SET status='closed' WHERE id=?",(fid,)); return redirect(request.referrer or ADMIN_PATH)

@app.get(ADMIN_PATH+'/simulate')
@admin_required
def simulate(): return render_template('simulate.html',sidebar=nav('admin'),enabled=q("SELECT value FROM settings WHERE key='simulate'",one=True)['value']=='1',page_theme='light')

@app.post(ADMIN_PATH+'/simulate/toggle')
@admin_required
def sim_toggle():
    val='1' if q("SELECT value FROM settings WHERE key='simulate'",one=True)['value']!='1' else '0'; db().execute("UPDATE settings SET value=? WHERE key='simulate'",(val,)); return redirect(url_for('simulate'))

@app.get(ADMIN_PATH+'/requests')
@admin_required
def admin_requests():
    rows=q("SELECT r.*,COALESCE(a.name,r.guest_name,'Guest') customer_name,p.id partner_id,pa.name partner_name FROM requests r LEFT JOIN accounts a ON a.id=r.customer_id LEFT JOIN partners p ON p.id=r.partner_id LEFT JOIN accounts pa ON pa.id=p.account_id ORDER BY r.id DESC LIMIT 250")
    return render_template('admin_requests.html',sidebar=nav('admin'),rows=rows,page_theme='light')

@app.get(ADMIN_PATH+'/customers')
@admin_required
def admin_customers():
    rows=q("SELECT a.id,a.name,a.username,a.phone,a.created_at,a.active,(SELECT count(*) FROM requests r WHERE r.customer_id=a.id) trips FROM accounts a WHERE a.role='customer' ORDER BY a.id DESC LIMIT 250")
    return render_template('admin_customers.html',sidebar=nav('admin'),rows=rows,page_theme='light')

@app.route(ADMIN_PATH+'/fare-controls',methods=['GET','POST'])
@admin_required
def admin_fares():
    if request.method=='POST':
        fields=['ride_base','ride_km','ride_min','drive_base','drive_km','drive_min','mover_base','mover_km','mover_min','mover_item','mover_helper','commission']
        for k in fields:
            v=request.form.get(k)
            if v not in (None,''):
                try: float(v); db().execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,v))
                except ValueError: pass
        return redirect(url_for('admin_fares'))
    vals={k:q('SELECT value FROM settings WHERE key=?',(k,),True)['value'] for k in ['ride_base','ride_km','ride_min','drive_base','drive_km','drive_min','mover_base','mover_km','mover_min','mover_item','mover_helper','commission']}
    return render_template('admin_fares.html',sidebar=nav('admin'),vals=vals,page_theme='light')

@app.get(ADMIN_PATH+'/backup')
@admin_required
def admin_backup():
    # Safe logical backup without exposing the SQLite file directly.
    data={}
    for table in ['accounts','partners','requests','ratings','feedback','events','settings','system_errors']:
        data[table]=[dict(r) for r in q(f'SELECT * FROM {table}')]
    payload=json.dumps({'created_at':now(),'data':data},default=str,indent=2)
    return app.response_class(payload,mimetype='application/json',headers={'Content-Disposition':'attachment; filename=O-System-backup.json'})

@app.get(ADMIN_PATH+'/export')
@admin_required
def admin_export():
    data={}
    for table in ['accounts','partners','requests','ratings','feedback','events','settings','system_errors']:
        data[table]=[dict(r) for r in q(f'SELECT * FROM {table}')]
    payload=json.dumps(data,default=str,indent=2)
    return app.response_class(payload,mimetype='application/json',headers={'Content-Disposition':'attachment; filename=O-System-export.json'})

@app.get(ADMIN_PATH+'/system')
@admin_required
def admin_system():
    errors=q("SELECT * FROM system_errors WHERE status='open' ORDER BY id DESC LIMIT 100")
    return render_template('admin_system.html',sidebar=nav('admin'),errors=errors,db_path=DB,page_theme='light')

@app.post(ADMIN_PATH+'/system/<int:eid>/resolve')
@admin_required
def resolve_error(eid): db().execute("UPDATE system_errors SET status='resolved' WHERE id=?",(eid,)); return redirect(url_for('admin_system'))


@app.errorhandler(500)
def server_error(e):
    add_error('server',request.path,500,request.method,'Unhandled server error')
    return render_template('error.html',sidebar=nav(),code=500,message='Something went wrong. The issue has been recorded for admin.',page_theme='light'),500

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'): return jsonify(ok=False,error='not_found'),404
    add_error('server',request.path,404,request.method,'Route not found')
    return render_template('error.html',sidebar=nav(),code=404,message='That page does not exist.',page_theme='light'),404

@app.errorhandler(403)
def forbidden(e): return render_template('error.html',sidebar=nav(),code=403,message='You do not have access to this area.',page_theme='light'),403

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT','10000')))
