from __future__ import annotations
import json, math, os, secrets, sqlite3, shutil, uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, jsonify, redirect, render_template, request, session, url_for, send_file

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('DATA_DIR', '/var/data' if os.environ.get('RENDER') else str(BASE_DIR / 'instance')))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / 'o.db'
BACKUP_DIR = DATA_DIR / 'backups'; BACKUP_DIR.mkdir(parents=True, exist_ok=True)
SECRET_FILE = DATA_DIR / 'secret.key'
if not SECRET_FILE.exists(): SECRET_FILE.write_text(secrets.token_urlsafe(48))
SECRET_KEY = os.environ.get('SECRET_KEY') or SECRET_FILE.read_text().strip()
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(MAX_CONTENT_LENGTH=5*1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')

SERVICES = {'bike':'O-Bikes','ride':'O-Ride','mover':'O-Movers'}
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
      email TEXT, password_hash TEXT, active INTEGER NOT NULL DEFAULT 1, verified INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL, last_seen TEXT
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
      cancel_reason TEXT, notes TEXT
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
    ''')
    defaults={
      'bike_base':'60','bike_per_km':'22','ride_base':'150','ride_per_km':'48',
      'mover_base':'700','mover_per_km':'70','mover_item_fee':'120','mover_helper_fee':'700','platform_commission':'10',
      'otravel_url':'https://otravel-bleg.onrender.com/','support_phone':'','app_name':'O'
    }
    for k,v in defaults.items(): c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)',(k,v))
    # first admin only; password can be replaced through settings later in code or DB.
    if not c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        pwd=os.environ.get('ADMIN_PASSWORD','ChangeMeNow!')
        c.execute("INSERT INTO users(role,name,phone,password_hash,active,verified,created_at) VALUES('admin',?,?,?,1,1,?)",('O Admin','admin',generate_password_hash(pwd),now()))
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

def login_required(fn):
    @wraps(fn)
    def w(*a,**kw):
        if not current_user(): return redirect(url_for('login', next=request.path))
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

def mask_phone(phone):
    if not phone: return ''
    return phone[:4]+'***'+phone[-2:]

@app.after_request
def security_headers(resp):
    resp.headers['X-Content-Type-Options']='nosniff'; resp.headers['X-Frame-Options']='SAMEORIGIN'; resp.headers['Referrer-Policy']='strict-origin-when-cross-origin'; return resp

@app.route('/health')
def health(): return jsonify(ok=True, service='O Mobility', time=now())

@app.route('/robots.txt')
def robots(): return app.response_class('User-agent: *\nAllow: /\nSitemap: '+url_for('sitemap',_external=True)+'\n',mimetype='text/plain')
@app.route('/sitemap.xml')
def sitemap():
    urls=[url_for('home',_external=True),url_for('service_page',service='bike',_external=True),url_for('service_page',service='ride',_external=True),url_for('service_page',service='mover',_external=True)]
    return app.response_class('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>{u}</loc></url>' for u in urls)+'</urlset>',mimetype='application/xml')

@app.route('/')
def home(): return render_template('home.html',otravel_url=setting('otravel_url'),user=current_user())
@app.route('/service/<service>')
def service_page(service):
    if service not in SERVICES: return 'Not found',404
    return render_template('service.html',service=service,name=SERVICES[service],user=current_user())

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        phone=request.form.get('phone','').strip(); pwd=request.form.get('password','')
        c=get_db(); u=c.execute('SELECT * FROM users WHERE phone=?',(phone,)).fetchone(); c.close()
        if u and u['active'] and u['password_hash'] and check_password_hash(u['password_hash'],pwd):
            session['uid']=u['id']; audit('login','user',u['id'],actor_id=u['id']); return redirect(url_for('dashboard'))
        return render_template('login.html',error='Invalid credentials or inactive account.')
    return render_template('login.html',error=None)
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('home'))
@app.route('/dashboard')
@login_required
def dashboard():
    u=current_user();
    if u['role']=='admin': return redirect(url_for('admin'))
    if u['role']=='driver': return redirect(url_for('driver_dashboard'))
    c=get_db(); rides=c.execute('SELECT r.*,d.name driver_name FROM requests r LEFT JOIN users d ON d.id=r.driver_id WHERE r.customer_id=? ORDER BY r.id DESC LIMIT 20',(u['id'],)).fetchall(); c.close()
    return render_template('customer_dashboard.html',user=u,rides=rides)

@app.route('/join',methods=['GET','POST'])
def join():
    if request.method=='POST':
        role=request.form.get('role','customer'); name=request.form.get('name','').strip(); phone=request.form.get('phone','').strip(); password=request.form.get('password','')
        if role not in ('customer','driver') or not name or not phone or len(password)<6: return render_template('join.html',error='Please complete the form. Password must be at least 6 characters.')
        c=get_db()
        try:
            cur=c.execute('INSERT INTO users(role,name,phone,password_hash,active,verified,created_at) VALUES(?,?,?,?,1,0,?)',(role,name,phone,generate_password_hash(password),now())); uid=cur.lastrowid
            if role=='driver':
                service=request.form.get('service','bike') if request.form.get('service') in SERVICES else 'bike'
                code='O'+secrets.token_hex(3).upper(); c.execute('INSERT INTO drivers(user_id,service,vehicle_label,plate,license_no,joined_code) VALUES(?,?,?,?,?,?)',(uid,service,request.form.get('vehicle_label','').strip(),request.form.get('plate','').strip(),request.form.get('license_no','').strip(),code))
            c.commit(); audit('signup','user',uid,f'role={role}',uid); c.close()
            return render_template('join_success.html', role=role)
        except sqlite3.IntegrityError:
            c.rollback(); c.close(); return render_template('join.html',error='That phone number is already registered.')
    return render_template('join.html',error=None)

@app.route('/api/estimate',methods=['POST'])
def api_estimate():
    data=request.get_json() or {}; service=data.get('service','bike'); km=float(data.get('distance_km') or 0); items=int(data.get('items') or 0); helpers=int(data.get('helpers') or 0)
    return jsonify(service=service, distance_km=km, fare=fare(service,km,items,helpers), commission_pct=float(setting('platform_commission','10')))

@app.route('/api/request',methods=['POST'])
def api_request():
    u=current_user()
    if not u or u['role']!='customer': return jsonify(error='Please sign in as a customer.'),401
    d=request.get_json() or {}; service=d.get('service');
    if service not in SERVICES: return jsonify(error='Invalid service.'),400
    pickup=(d.get('pickup') or '').strip(); dest=(d.get('destination') or '').strip()
    plat=d.get('pickup_lat'); plng=d.get('pickup_lng'); dlat=d.get('dest_lat'); dlng=d.get('dest_lng')
    if not pickup or not dest: return jsonify(error='Pickup and destination are required.'),400
    km=haversine(float(plat),float(plng),float(dlat),float(dlng)) if None not in (plat,plng,dlat,dlng) else float(d.get('distance_km') or 0)
    amount=fare(service,km,int(d.get('items') or 0),int(d.get('helpers') or 0))
    c=get_db(); cur=c.execute('INSERT INTO requests(customer_id,service,pickup,destination,pickup_lat,pickup_lng,dest_lat,dest_lng,distance_km,fare,customer_offer,payment_method,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(u['id'],service,pickup,dest,plat,plng,dlat,dlng,km,amount,d.get('customer_offer'),d.get('payment_method','cash'),d.get('notes',''),now())); rid=cur.lastrowid; c.commit(); c.close()
    drv=find_driver(service,float(plat) if plat is not None else None,float(plng) if plng is not None else None)
    if drv:
        c=get_db(); c.execute("UPDATE requests SET driver_id=?,status='assigned',accepted_at=NULL WHERE id=?",(drv['user_id'],rid)); c.commit(); c.close(); notify(drv['user_id'],'ride','New O request',f'{SERVICES[service]} request near you: {pickup}',rid)
    audit('request_created','request',rid,f'service={service};fare={amount};driver={drv["user_id"] if drv else None}',u['id'])
    return jsonify(ok=True,request_id=rid,fare=amount,status='assigned' if drv else 'searching',driver={'name':drv['name'],'phone':mask_phone(drv['phone'])} if drv else None)

@app.route('/api/request/<int:rid>')
@login_required
def request_status(rid):
    u=current_user(); c=get_db(); r=c.execute('SELECT r.*,d.name driver_name FROM requests r LEFT JOIN users d ON d.id=r.driver_id WHERE r.id=? AND (r.customer_id=? OR r.driver_id=?)',(rid,u['id'],u['id'])).fetchone(); c.close()
    if not r: return jsonify(error='Not found'),404
    return jsonify(request=dict(r))

@app.route('/api/request/<int:rid>/action',methods=['POST'])
@login_required
def request_action(rid):
    u=current_user(); action=(request.get_json() or {}).get('action'); c=get_db(); r=c.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
    if not r: c.close(); return jsonify(error='Not found'),404
    if u['role']=='driver' and r['driver_id']==u['id']:
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

@app.route('/driver')
@login_required
def driver_dashboard():
    u=current_user();
    if u['role']!='driver': return redirect(url_for('dashboard'))
    c=get_db(); d=c.execute('SELECT d.*,u.name,u.phone,u.verified,u.active FROM drivers d JOIN users u ON u.id=d.user_id WHERE d.user_id=?',(u['id'],)).fetchone(); jobs=c.execute('SELECT r.*,u.name customer_name FROM requests r JOIN users u ON u.id=r.customer_id WHERE r.driver_id=? ORDER BY r.id DESC LIMIT 30',(u['id'],)).fetchall(); c.close()
    return render_template('driver_dashboard.html',user=u,driver=d,jobs=jobs)
@app.route('/api/driver/presence',methods=['POST'])
@login_required
def driver_presence():
    u=current_user();
    if u['role']!='driver': return jsonify(error='No'),403
    d=request.get_json() or {}; status=d.get('status','offline'); lat=d.get('lat'); lng=d.get('lng')
    if status not in ('available','offline','on_trip'): return jsonify(error='Invalid status'),400
    c=get_db(); c.execute('UPDATE drivers SET status=?,lat=?,lng=? WHERE user_id=?',(status,lat,lng,u['id'])); c.execute('UPDATE users SET last_seen=? WHERE id=?',(now(),u['id'])); c.commit(); c.close(); return jsonify(ok=True,status=status)

@app.route('/api/request/<int:rid>/rate',methods=['POST'])
@login_required
def rate_request(rid):
    u=current_user(); d=request.get_json() or {}; app_rating=max(1,min(5,int(d.get('app_rating') or 0))); rider_rating=d.get('rider_rating'); rider_rating=max(1,min(5,int(rider_rating))) if rider_rating else None
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

@app.route('/admin/login',methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        c=get_db(); u=c.execute("SELECT * FROM users WHERE role='admin' AND phone='admin'").fetchone(); c.close()
        if u and check_password_hash(u['password_hash'],request.form.get('password','')): session['uid']=u['id']; return redirect(url_for('admin'))
        return render_template('admin_login.html',error='Invalid admin password.')
    return render_template('admin_login.html',error=None)
@app.route('/api/admin/live')
@admin_required
def admin_live():
    c=get_db(); rows=c.execute("SELECT d.user_id,d.service,d.status,d.lat,d.lng,d.rating,u.name,u.active,u.verified FROM drivers d JOIN users u ON u.id=d.user_id WHERE u.active=1 AND d.lat IS NOT NULL AND d.lng IS NOT NULL").fetchall(); c.close(); return jsonify(items=[dict(r) for r in rows])

@app.route('/admin')
@admin_required
def admin():
    c=get_db(); stats={
      'drivers':c.execute("SELECT COUNT(*) n FROM users WHERE role='driver'").fetchone()['n'],
      'customers':c.execute("SELECT COUNT(*) n FROM users WHERE role='customer'").fetchone()['n'],
      'active_drivers':c.execute("SELECT COUNT(*) n FROM drivers d JOIN users u ON u.id=d.user_id WHERE u.active=1 AND d.status='available'").fetchone()['n'],
      'open_requests':c.execute("SELECT COUNT(*) n FROM requests WHERE status IN ('searching','assigned','accepted','on_trip')").fetchone()['n'],
      'completed':c.execute("SELECT COUNT(*) n FROM requests WHERE status='completed'").fetchone()['n'],
      'complaints':c.execute("SELECT COUNT(*) n FROM complaints WHERE status='open'").fetchone()['n'],
    }
    drivers=c.execute("SELECT d.*,u.name,u.phone,u.active,u.verified,u.created_at FROM drivers d JOIN users u ON u.id=d.user_id ORDER BY u.id DESC").fetchall()
    requests=c.execute("SELECT r.*,u.name customer_name,d.name driver_name FROM requests r JOIN users u ON u.id=r.customer_id LEFT JOIN users d ON d.id=r.driver_id ORDER BY r.id DESC LIMIT 100").fetchall()
    complaints=c.execute("SELECT c.*,u.name FROM complaints c JOIN users u ON u.id=c.user_id ORDER BY c.id DESC LIMIT 50").fetchall(); c.close()
    settings={k:setting(k) for k in ['bike_base','bike_per_km','ride_base','ride_per_km','mover_base','mover_per_km','mover_item_fee','mover_helper_fee','platform_commission','otravel_url']}
    return render_template('admin.html',stats=stats,drivers=drivers,requests=requests,complaints=complaints,settings=settings)
@app.route('/admin/driver/<int:uid>/action',methods=['POST'])
@admin_required
def admin_driver_action(uid):
    action=request.form.get('action'); c=get_db();
    if action=='verify': c.execute('UPDATE users SET verified=1 WHERE id=? AND role=\'driver\'',(uid,))
    elif action=='deactivate': c.execute("UPDATE users SET active=0 WHERE id=?",(uid,)); c.execute("UPDATE drivers SET status='offline',deactivated_reason=? WHERE user_id=?",(request.form.get('reason','admin action'),uid))
    elif action=='reactivate': c.execute('UPDATE users SET active=1 WHERE id=?',(uid,))
    c.commit(); c.close(); audit('driver_'+action,'user',uid,actor_id=current_user()['id']); return redirect(url_for('admin'))
@app.route('/admin/complaint/<int:cid>',methods=['POST'])
@admin_required
def admin_complaint(cid):
    c=get_db(); c.execute("UPDATE complaints SET status='resolved',admin_note=?,resolved_at=? WHERE id=?",(request.form.get('note',''),now(),cid)); c.commit(); c.close(); audit('complaint_resolved','complaint',cid,actor_id=current_user()['id']); return redirect(url_for('admin'))
@app.route('/admin/settings',methods=['POST'])
@admin_required
def admin_settings():
    keys=['bike_base','bike_per_km','ride_base','ride_per_km','mover_base','mover_per_km','mover_item_fee','mover_helper_fee','platform_commission','otravel_url']
    c=get_db();
    for k in keys:
        if k in request.form: c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,request.form[k].strip()))
    c.commit(); c.close(); audit('settings_updated','settings',actor_id=current_user()['id']); return redirect(url_for('admin'))
@app.route('/admin/backup')
@admin_required
def admin_backup():
    ts=datetime.now().strftime('%Y%m%d-%H%M%S'); dest=BACKUP_DIR/f'o-{ts}.sqlite3'; src=get_db();
    dst=sqlite3.connect(dest); src.backup(dst); dst.close(); src.close(); audit('backup_created','backup',details=str(dest.name),actor_id=current_user()['id']); return send_file(dest,as_attachment=True,download_name=dest.name)
@app.route('/admin/export')
@admin_required
def admin_export():
    c=get_db(); payload={}
    for t in ['users','drivers','requests','ratings','complaints','notifications','audits','settings']:
        payload[t]=[dict(r) for r in c.execute(f'SELECT * FROM {t}').fetchall()]
    c.close(); p=BACKUP_DIR/f'export-{datetime.now().strftime("%Y%m%d-%H%M%S")}.json'; p.write_text(json.dumps(payload,default=str,indent=2)); return send_file(p,as_attachment=True,download_name=p.name)

@app.route('/logout-all')
def noop(): return redirect(url_for('home'))

if __name__=='__main__': app.run(debug=True)
