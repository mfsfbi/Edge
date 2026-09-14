import os, sqlite3, math, json, urllib.parse, urllib.request, secrets
from functools import wraps
from datetime import datetime, timezone
from flask import Flask, g, render_template, request, redirect, url_for, session, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash

app=Flask(__name__, template_folder='app/templates', static_folder='app/static')
ADMIN_PATH='/promise212324'
ADMIN_USER=os.environ.get('USER_NAME','admin')
ADMIN_PASS=os.environ.get('PASSWORD','change-me')
app.secret_key=secrets.token_hex(32) if not (os.environ.get('USER_NAME') and os.environ.get('PASSWORD')) else generate_password_hash(ADMIN_USER+'|'+ADMIN_PASS)[:64]

BASE=os.path.dirname(os.path.abspath(__file__))
DATA='/var/data' if os.path.isdir('/var/data') and os.access('/var/data',os.W_OK) else os.path.join(BASE,'instance')
os.makedirs(DATA,exist_ok=True)
DB=os.path.join(DATA,'o_system_v1.db')
SERVICES={'ride':'O-Ride','drive':'O-Drive','mover':'O-Movers'}
SERVICE_PATHS={'ride':'/O-Ride','drive':'/O-Drive','mover':'/O-Movers'}
SERVICE_ICONS={'ride':'🏍️','drive':'🚗','mover':'🚚','travel':'✈️'}
SERVICE_COLORS={'ride':'gold','drive':'green','mover':'blue','travel':'primary'}

SCHEMA='''
CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, service TEXT, phone TEXT, created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS partners(id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER UNIQUE NOT NULL, service TEXT NOT NULL, vehicle TEXT, plate TEXT, licence TEXT, rating REAL NOT NULL DEFAULT 5.0, completed INTEGER NOT NULL DEFAULT 0, earnings REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'offline', lat REAL, lon REAL, last_seen TEXT, FOREIGN KEY(account_id) REFERENCES accounts(id));
CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, guest_name TEXT, service TEXT NOT NULL, pickup_name TEXT, destination_name TEXT, pickup_lat REAL, pickup_lon REAL, dest_lat REAL, dest_lon REAL, fare REAL, payment TEXT, status TEXT NOT NULL DEFAULT 'requested', partner_id INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY(customer_id) REFERENCES accounts(id), FOREIGN KEY(partner_id) REFERENCES partners(id));
CREATE TABLE IF NOT EXISTS ratings(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, partner_id INTEGER, request_id INTEGER, app_rating INTEGER, partner_rating INTEGER, note TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, guest_name TEXT, kind TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, role TEXT, page TEXT, service TEXT, device TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
'''

def db():
 if 'db' not in g:
  g.db=sqlite3.connect(DB); g.db.row_factory=sqlite3.Row; g.db.executescript(SCHEMA); g.db.commit()
 return g.db
@app.teardown_appcontext
def close_db(exc):
 conn=g.pop('db',None)
 if conn: conn.close()

def now(): return datetime.now(timezone.utc).isoformat()
def q(sql,args=(),one=False):
 cur=db().execute(sql,args); rows=cur.fetchall(); return (rows[0] if rows else None) if one else rows
def nav(role='customer',service=None):
 if role=='admin':
  return '''<nav><a class="navbtn active" href="/promise212324">Overview <span>⌂</span></a><div class="navsection"><h4>O Services</h4><a class="navbtn" href="/promise212324/service/ride">O-Ride <span>›</span></a><a class="navbtn" href="/promise212324/service/drive">O-Drive <span>›</span></a><a class="navbtn" href="/promise212324/service/mover">O-Movers <span>›</span></a></div><div class="navsection"><h4>Control</h4><a class="navbtn" href="/promise212324/inbox">Inbox <span>›</span></a><a class="navbtn" href="/promise212324/complaints">Complaints <span>›</span></a><a class="navbtn" href="/promise212324/partners">Partners <span>›</span></a><a class="navbtn" href="/promise212324/people">People & usage <span>›</span></a><a class="navbtn" href="/promise212324/simulate">Simulate <span>›</span></a><a class="navbtn" href="/promise212324/system">System <span>›</span></a></div></nav>'''
 if role=='partner':
  return f'''<nav><a class="navbtn active" href="{SERVICE_PATHS.get(service,'/')}">{SERVICES.get(service,service or 'Partner')} Dashboard <span>⌂</span></a><a class="navbtn" href="/partner/requests">Requests <span>›</span></a><a class="navbtn" href="/partner/earnings">Earnings <span>›</span></a><a class="navbtn" href="/partner/ratings">Ratings <span>›</span></a><a class="navbtn" href="/partner/help">Help <span>›</span></a><a class="navbtn" href="/logout">Sign out <span>↗</span></a></nav>'''
 logged='''<nav><a class="navbtn active" href="/services">Services <span>⌂</span></a><a class="navbtn" href="/customer/trips">My trips <span>›</span></a><a class="navbtn" href="/customer/ratings">Ratings & feedback <span>›</span></a><a class="navbtn" href="/help">Help, concern or request <span>›</span></a><a class="navbtn" href="/logout">Sign out <span>↗</span></a></nav>'''
 guest='''<nav><a class="navbtn active" href="/services">Services <span>⌂</span></a><a class="navbtn" href="/login">Sign in <span>›</span></a><a class="navbtn" href="/account/register">Create account <span>›</span></a><a class="navbtn" href="/help">Help, concern or request <span>›</span></a></nav>'''
 return logged if session.get('account_id') else guest

def actor():
 aid=session.get('account_id'); return q('SELECT * FROM accounts WHERE id=? AND active=1',(aid,),True) if aid else None

def log_event(page,service=None):
 a=actor(); ua=request.headers.get('User-Agent','')[:120]
 try: db().execute('INSERT INTO events(customer_id,role,page,service,device,created_at) VALUES(?,?,?,?,?,?)',(a['id'] if a else None,a['role'] if a else 'guest',page,service,ua,now())); db().commit()
 except Exception: pass

def login_required(role=None):
 def deco(fn):
  @wraps(fn)
  def inner(*args,**kwargs):
   a=actor()
   if not a: return redirect(url_for('login',next=request.path))
   if role and a['role']!=role: abort(403)
   return fn(*args,**kwargs)
  return inner
 return deco

def admin_required(fn):
 @wraps(fn)
 def inner(*args,**kwargs):
  if not session.get('admin'): return redirect(url_for('admin_login',next=request.path))
  return fn(*args,**kwargs)
 return inner

def ensure_defaults():
 db().execute("INSERT OR IGNORE INTO settings(key,value) VALUES('simulate','0')")
 db().commit()

@app.before_request

def before(): db(); ensure_defaults()

@app.get('/health')
def health(): return jsonify(ok=True,version='O-System V1')

@app.get('/')
def home():
 log_event('home'); return render_template('home.html',sidebar=nav())

@app.get('/services')
def services():
 log_event('services'); return render_template('services.html',sidebar=nav())

@app.route('/account/register',methods=['GET','POST'])
def register():
 err=''
 if request.method=='POST':
  name=request.form.get('name','').strip(); username=request.form.get('username','').strip().lower(); phone=request.form.get('phone','').strip(); pw=request.form.get('password','')
  if not name or not username or len(pw)<6: err='Enter your name, username and a password of at least 6 characters.'
  elif q('SELECT id FROM accounts WHERE username=?',(username,),True): err='That username is already in use.'
  else:
   db().execute('INSERT INTO accounts(name,username,password_hash,role,phone,created_at) VALUES(?,?,?,?,?,?)',(name,username,generate_password_hash(pw),'customer',phone,now())); db().commit(); a=q('SELECT * FROM accounts WHERE username=?',(username,),True); session['account_id']=a['id']; return redirect(url_for('services'))
 return render_template('register.html',sidebar=nav(),error=err)

@app.route('/login',methods=['GET','POST'])
def login():
 err=''; next_url=request.args.get('next','/services')
 if request.method=='POST':
  identifier=request.form.get('username','').strip().lower(); pw=request.form.get('password','')
  a=q('SELECT * FROM accounts WHERE lower(username)=? AND active=1',(identifier,),True)
  if a and check_password_hash(a['password_hash'],pw):
   session['account_id']=a['id']
   if a['role']=='partner': return redirect(SERVICE_PATHS.get(a['service'],'/services'))
   return redirect(next_url if next_url.startswith('/') else '/services')
  err='The name/username or password is not correct.'
 return render_template('login.html',sidebar=nav(),error=err)

@app.get('/partner-login')
def partner_login(): return redirect(url_for('login'))
@app.get('/logout')
def logout(): session.clear(); return redirect(url_for('home'))

@app.route('/account',methods=['GET','POST'])
@login_required('customer')
def account_page():
 a=actor(); msg=None; err=None
 if request.method=='POST':
  name=request.form.get('name','').strip(); phone=request.form.get('phone','').strip()
  if not name: err='Name is required.'
  else:
   db().execute('UPDATE accounts SET name=?,phone=? WHERE id=?',(name,phone,a['id'])); db().commit(); msg='Account updated.'; a=actor()
 return render_template('account.html',sidebar=nav(),account=a,error=err,success=msg)

@app.post('/api/app-rating')
@login_required('customer')
def app_rating():
 data=request.get_json(silent=True) or request.form; value=int(data.get('rating',0) or 0); note=(data.get('note') or '').strip()
 if value not in (1,2,3,4,5): return jsonify(ok=False,error='Choose a rating from 1 to 5.'),400
 db().execute('INSERT INTO ratings(customer_id,app_rating,note,created_at) VALUES(?,?,?,?)',(actor()['id'],value,note,now())); db().commit(); return jsonify(ok=True)

@app.get('/customer/trips')
@login_required('customer')
def trips():
 rows=q('SELECT r.*,p.id pid,a.name partner_name FROM requests r LEFT JOIN partners p ON p.id=r.partner_id LEFT JOIN accounts a ON a.id=p.account_id WHERE r.customer_id=? ORDER BY r.id DESC LIMIT 30',(actor()['id'],))
 return render_template('trips.html',sidebar=nav(),trips=rows)

@app.get('/customer/ratings')
@login_required('customer')
def ratings_page():
 rows=q('SELECT r.*,a.name partner_name FROM ratings x LEFT JOIN requests r ON r.id=x.request_id LEFT JOIN partners p ON p.id=x.partner_id LEFT JOIN accounts a ON a.id=p.account_id WHERE x.customer_id=? ORDER BY x.id DESC',(actor()['id'],))
 completed=q("SELECT r.*,a.name partner_name,p.id partner_id FROM requests r LEFT JOIN partners p ON p.id=r.partner_id LEFT JOIN accounts a ON a.id=p.account_id WHERE r.customer_id=? AND r.status='completed' ORDER BY r.id DESC",(actor()['id'],))
 return render_template('ratings.html',sidebar=nav(),ratings=rows,completed=completed)

@app.post('/api/rate')
@login_required('customer')
def rate():
 data=request.get_json(silent=True) or request.form; rid=int(data.get('request_id')); app_rating=int(data.get('app_rating',0) or 0); pr=int(data.get('partner_rating',0) or 0); note=(data.get('note') or '').strip()
 r=q("SELECT * FROM requests WHERE id=? AND customer_id=? AND status='completed'",(rid,actor()['id']),True)
 if not r: return jsonify(ok=False,error='Trip not found'),404
 db().execute('INSERT INTO ratings(customer_id,partner_id,request_id,app_rating,partner_rating,note,created_at) VALUES(?,?,?,?,?,?,?)',(actor()['id'],r['partner_id'],rid,app_rating or None,pr or None,note,now())); db().commit(); return jsonify(ok=True)

@app.route('/help',methods=['GET','POST'])
def help_page():
 err=''
 if request.method=='POST':
  a=actor(); kind=request.form.get('kind','concern'); msg=request.form.get('message','').strip(); guest=request.form.get('guest_name','').strip()
  if not msg: err='Please tell us what you need.'
  else: db().execute('INSERT INTO feedback(customer_id,guest_name,kind,message,created_at) VALUES(?,?,?,?,?)',(a['id'] if a else None,guest,kind,msg,now())); db().commit(); return render_template('help.html',sidebar=nav(),success='Your message has been sent to O.',error='')
 return render_template('help.html',sidebar=nav(),error=err,success=None)


@app.get('/service/<service>')

def customer_service(service):
 if service not in SERVICES: abort(404)
 log_event('service',service)
 return render_template('service.html',sidebar=nav(),service=service,service_name=SERVICES[service])

# Provider entry points are the only public provider links in V1.
@app.route('/O-Ride',methods=['GET'])
@app.route('/O-Drive',methods=['GET'])
@app.route('/O-Movers',methods=['GET'])
def provider_entry():
 path=request.path.lower(); service='ride' if 'ride' in path else 'drive' if 'drive' in path else 'mover'
 a=actor()
 if a and a['role']=='partner':
  if a['service']!=service: return redirect(SERVICE_PATHS[a['service']])
  return redirect(url_for('partner_home',service=service))
 return render_template('provider_entry.html',sidebar=nav(),service=service,service_name=SERVICES[service],action=SERVICE_PATHS[service])

@app.post('/provider-login')
def provider_login_post():
 service=request.form.get('service'); identifier=request.form.get('username','').strip().lower(); pw=request.form.get('password','')
 a=q('SELECT * FROM accounts WHERE lower(username)=? AND active=1 AND role=\'partner\'',(identifier,),True)
 if a and a['service']==service and check_password_hash(a['password_hash'],pw): session['account_id']=a['id']; return redirect(url_for('partner_home',service=service))
 return render_template('provider_entry.html',sidebar=nav(),service=service,service_name=SERVICES[service],action=SERVICE_PATHS[service],error='Partner name/username or password is not correct.')

@app.get('/partner/<service>')
@login_required('partner')
def partner_home(service):
 a=actor(); p=q('SELECT p.*,a.name FROM partners p JOIN accounts a ON a.id=p.account_id WHERE p.account_id=?',(a['id'],),True)
 if not p or p['service']!=service: abort(403)
 reqs=q("SELECT r.*,a.name customer_name FROM requests r LEFT JOIN accounts a ON a.id=r.customer_id WHERE r.service=? AND (r.partner_id=? OR (r.partner_id IS NULL AND r.status='requested')) ORDER BY CASE WHEN r.partner_id=? THEN 0 ELSE 1 END,r.id DESC LIMIT 30",(service,p['id'],p['id']))
 return render_template('partner.html',sidebar=nav('partner',service),partner=p,requests=reqs,service=service,service_name=SERVICES[service])

@app.post('/api/partner/status')
@login_required('partner')
def partner_status():
 a=actor(); p=q('SELECT * FROM partners WHERE account_id=?',(a['id'],),True); data=request.get_json() or {}; status=data.get('status','orange'); lat=data.get('lat'); lon=data.get('lon')
 if status not in ('offline','orange','green','blue'): status='orange'
 db().execute('UPDATE partners SET status=?,lat=?,lon=?,last_seen=? WHERE id=?',(status,lat,lon,now(),p['id'])); db().commit(); return jsonify(ok=True)

@app.post('/api/partner/request')
@login_required('partner')
def partner_request():
 a=actor(); p=q('SELECT * FROM partners WHERE account_id=?',(a['id'],),True); data=request.get_json() or {}; rid=int(data.get('request_id')); act=data.get('action')
 r=q('SELECT * FROM requests WHERE id=? AND service=?',(rid,p['service']),True)
 if not r: return jsonify(ok=False,error='Request not found'),404
 if act=='accept' and (r['status']=='requested'):
  db().execute('UPDATE requests SET partner_id=?,status=\'assigned\',updated_at=? WHERE id=?',(p['id'],now(),rid)); db().execute('UPDATE partners SET status=\'green\' WHERE id=?',(p['id'],)); db().commit()
 elif act=='start' and r['partner_id']==p['id']: db().execute('UPDATE requests SET status=\'on_trip\',updated_at=? WHERE id=?',(now(),rid)); db().execute('UPDATE partners SET status=\'blue\' WHERE id=?',(p['id'],)); db().commit()
 elif act=='complete' and r['partner_id']==p['id']:
  db().execute('UPDATE requests SET status=\'completed\',updated_at=? WHERE id=?',(now(),rid)); db().execute('UPDATE partners SET status=\'orange\',completed=completed+1,earnings=earnings+COALESCE(?,0) WHERE id=?',(r['fare'],p['id'])); db().commit()
 elif act=='decline': pass
 return jsonify(ok=True)

@app.get('/partner/requests')
@login_required('partner')
def partner_requests(): return redirect(url_for('partner_home',service=actor()['service']))
@app.get('/partner/earnings')
@login_required('partner')
def partner_earnings():
 a=actor(); p=q('SELECT * FROM partners WHERE account_id=?',(a['id'],),True); return render_template('partner_info.html',sidebar=nav('partner',p['service']),heading='Earnings',partner=p,service=p['service'],message=f"KES {p['earnings']:.0f} recorded on completed trips.")
@app.get('/partner/ratings')
@login_required('partner')
def partner_ratings():
 a=actor(); p=q('SELECT * FROM partners WHERE account_id=?',(a['id'],),True); rows=q('SELECT x.*,a.name customer_name FROM ratings x LEFT JOIN accounts a ON a.id=x.customer_id WHERE x.partner_id=? ORDER BY x.id DESC',(p['id'],)); return render_template('partner_ratings.html',sidebar=nav('partner',p['service']),partner=p,rows=rows)
@app.get('/partner/help')
@login_required('partner')
def partner_help(): return redirect(url_for('help_page'))

@app.get('/api/partners/nearby')
def nearby_partners():
 service=request.args.get('service'); lat=float(request.args.get('lat','0')); lon=float(request.args.get('lon','0'))
 rows=q("SELECT p.*,a.name FROM partners p JOIN accounts a ON a.id=p.account_id WHERE p.service=? AND a.active=1 AND p.status='orange' AND p.lat IS NOT NULL AND p.lon IS NOT NULL",(service,))
 out=[]
 for p in rows:
  d=math.hypot((p['lat']-lat)*111,(p['lon']-lon)*111*math.cos(math.radians(lat))); out.append({'id':p['id'],'name':p['name'],'lat':p['lat'],'lon':p['lon'],'distance_km':round(d,2),'rating':p['rating']})
 return jsonify(sorted(out,key=lambda x:x['distance_km'])[:10])

@app.get('/api/request/<int:rid>')
def request_status(rid):
 r=q('SELECT r.*,p.lat partner_lat,p.lon partner_lon,p.status partner_status,a.name partner_name FROM requests r LEFT JOIN partners p ON p.id=r.partner_id LEFT JOIN accounts a ON a.id=p.account_id WHERE r.id=?',(rid,),True)
 if not r: return jsonify(ok=False),404
 return jsonify(dict(r))

@app.get('/api/geocode/search')
def geocode_search():
 qv=request.args.get('q','').strip()
 if not qv: return jsonify([])
 try:
  url='https://nominatim.openstreetmap.org/search?'+urllib.parse.urlencode({'q':qv+', Kenya','format':'json','limit':5})
  req=urllib.request.Request(url,headers={'User-Agent':'O-System-V1/1.0'})
  with urllib.request.urlopen(req,timeout=8) as r: data=json.load(r)
  return jsonify([{'name':x.get('display_name',''),'lat':float(x['lat']),'lon':float(x['lon'])} for x in data])
 except Exception as e: return jsonify([])

@app.get('/api/route')
def route_api():
 try:
  a=(float(request.args['olat']),float(request.args['olon'])); b=(float(request.args['dlat']),float(request.args['dlon']))
  coords=f'{a[1]},{a[0]};{b[1]},{b[0]}'
  url='https://router.project-osrm.org/route/v1/driving/'+coords+'?overview=full&geometries=geojson'
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'O-System-V1/1.0'}),timeout=10) as r: data=json.load(r)
  rt=data['routes'][0]; return jsonify(distance_km=rt['distance']/1000,duration_min=rt['duration']/60,geometry=[[p[1],p[0]] for p in rt['geometry']['coordinates']])
 except Exception: return jsonify(error='road_route_unavailable'),503

@app.post('/api/request')
def create_request():
 data=request.get_json() or {}; service=data.get('service');
 if service not in SERVICES: return jsonify(ok=False,error='Invalid service'),400
 pickup=data.get('pickup') or {}; dest=data.get('destination') or {}; a=actor(); guest=data.get('guest_name','').strip()
 if not (pickup.get('lat') is not None and pickup.get('lon') is not None and dest.get('lat') is not None and dest.get('lon') is not None): return jsonify(ok=False,error='Choose pickup and destination on the map'),400
 # fare is derived from routed distance when available; no hidden price.
 dist=float(data.get('distance_km') or 0)
 rates={'ride':(55,18,60),'drive':(110,42,150),'mover':(600,60,700)}; base,pkm,mn=rates[service]; fare=max(mn,base+dist*pkm)
 t=now(); cur=db().execute('INSERT INTO requests(customer_id,guest_name,service,pickup_name,destination_name,pickup_lat,pickup_lon,dest_lat,dest_lon,fare,payment,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(a['id'] if a else None,guest,service,pickup.get('name','Pickup'),dest.get('name','Destination'),pickup['lat'],pickup['lon'],dest['lat'],dest['lon'],round(fare/10)*10,data.get('payment','Cash'),'requested',t,t)); rid=cur.lastrowid
 # Match nearest available partner.
 partners=q("SELECT p.*,a.name FROM partners p JOIN accounts a ON a.id=p.account_id WHERE p.service=? AND a.active=1 AND p.status='orange' AND p.lat IS NOT NULL AND p.lon IS NOT NULL",(service,)); best=None; bd=None
 for p in partners:
  d=math.hypot((p['lat']-pickup['lat'])*111,(p['lon']-pickup['lon'])*111*math.cos(math.radians(pickup['lat'])))
  if bd is None or d<bd: bd=d; best=p
 if best:
  db().execute('UPDATE requests SET partner_id=?,status=\'assigned\',updated_at=? WHERE id=?',(best['id'],t,rid)); db().execute('UPDATE partners SET status=\'green\' WHERE id=?',(best['id'],))
 db().commit(); return jsonify(ok=True,id=rid,fare=round(fare/10)*10,assigned=best['name'] if best else None,status='assigned' if best else 'requested')

# Admin
@app.route(ADMIN_PATH,methods=['GET','POST'])
def admin_login():
 if session.get('admin'):
  stats={'customers':q("SELECT count(*) c FROM accounts WHERE role='customer'",one=True)['c'],'partners':q("SELECT count(*) c FROM accounts WHERE role='partner'",one=True)['c'],'open_requests':q("SELECT count(*) c FROM requests WHERE status IN ('requested','assigned','on_trip')",one=True)['c'],'open_feedback':q("SELECT count(*) c FROM feedback WHERE status='open'",one=True)['c'],'pwa':0}
  return render_template('admin.html',sidebar=nav('admin'),stats=stats)
 err=''
 if request.method=='POST':
  if request.form.get('username')==ADMIN_USER and request.form.get('password')==ADMIN_PASS:
   session['admin']=True; return redirect(ADMIN_PATH)
  err='Admin credentials are not correct.'
 return render_template('admin_login.html',sidebar='',error=err)
@app.get('/admin')
def admin_block(): abort(404)
@app.get(ADMIN_PATH+'/logout')
def admin_logout(): session.pop('admin',None); return redirect(url_for('admin_login'))

@app.get(ADMIN_PATH+'/service/<service>')
@admin_required
def admin_service(service):
 if service not in SERVICES: abort(404)
 reqs=q("SELECT r.*,COALESCE(c.name,r.guest_name,'Guest') customer_name,p.id partner_id,pa.name partner_name,p.status partner_status,p.lat partner_lat,p.lon partner_lon FROM requests r LEFT JOIN accounts c ON c.id=r.customer_id LEFT JOIN partners p ON p.id=r.partner_id LEFT JOIN accounts pa ON pa.id=p.account_id WHERE r.service=? ORDER BY r.id DESC LIMIT 80",(service,))
 partners=q("SELECT p.*,a.name,a.username,a.active a_active FROM partners p JOIN accounts a ON a.id=p.account_id WHERE p.service=? ORDER BY a.name",(service,))
 return render_template('admin_service.html',sidebar=nav('admin'),service=service,service_name=SERVICES[service],requests=reqs,partners=partners)

@app.route(ADMIN_PATH+'/partners',methods=['GET','POST'])
@admin_required
def admin_partners():
 if request.method=='POST':
  name=request.form.get('name','').strip(); username=request.form.get('username','').strip().lower(); pw=request.form.get('password',''); service=request.form.get('service')
  if name and username and pw and service in SERVICES and not q('SELECT id FROM accounts WHERE username=?',(username,),True):
   cur=db().execute('INSERT INTO accounts(name,username,password_hash,role,phone,created_at) VALUES(?,?,?,?,?,?)',(name,username,generate_password_hash(pw),'partner',request.form.get('phone',''),now())); aid=cur.lastrowid; db().execute('INSERT INTO partners(account_id,service,vehicle,plate,licence,status) VALUES(?,?,?,?,?,\'orange\')',(aid,service,request.form.get('vehicle',''),request.form.get('plate',''),request.form.get('licence',''))); db().commit()
 partners=q('SELECT p.*,a.name,a.username,a.active,a.phone FROM partners p JOIN accounts a ON a.id=p.account_id ORDER BY p.service,a.name')
 return render_template('admin_partners.html',sidebar=nav('admin'),partners=partners)

@app.post(ADMIN_PATH+'/partner/<int:pid>/toggle')
@admin_required
def toggle_partner(pid):
 p=q('SELECT * FROM partners WHERE id=?',(pid,),True)
 if not p: abort(404)
 a=q('SELECT * FROM accounts WHERE id=?',(p['account_id'],),True); new=0 if a['active'] else 1; db().execute('UPDATE accounts SET active=? WHERE id=?',(new,a['id'])); db().execute('UPDATE partners SET status=? WHERE id=?',('orange' if new else 'offline',pid)); db().commit(); return redirect(url_for('admin_partners'))

@app.get(ADMIN_PATH+'/people')
@admin_required
def admin_people():
 people=q('SELECT e.*,COALESCE(a.name,e.role) display_name FROM events e LEFT JOIN accounts a ON a.id=e.customer_id ORDER BY e.id DESC LIMIT 120'); return render_template('admin_people.html',sidebar=nav('admin'),people=people)

@app.get(ADMIN_PATH+'/inbox')
@admin_required
def admin_inbox():
 rows=q('SELECT f.*,a.name account_name FROM feedback f LEFT JOIN accounts a ON a.id=f.customer_id ORDER BY f.id DESC LIMIT 120'); return render_template('admin_feedback.html',sidebar=nav('admin'),heading='Inbox',rows=rows,mode='inbox')
@app.get(ADMIN_PATH+'/complaints')
@admin_required
def admin_complaints():
 rows=q("SELECT f.*,a.name account_name FROM feedback f LEFT JOIN accounts a ON a.id=f.customer_id WHERE f.kind='complaint' ORDER BY f.id DESC LIMIT 120"); return render_template('admin_feedback.html',sidebar=nav('admin'),heading='Complaints',rows=rows,mode='complaints')
@app.post(ADMIN_PATH+'/feedback/<int:fid>/close')
@admin_required
def close_feedback(fid): db().execute("UPDATE feedback SET status='closed' WHERE id=?",(fid,)); db().commit(); return redirect(request.referrer or url_for('admin_login'))

@app.get(ADMIN_PATH+'/simulate')
@admin_required
def simulate(): return render_template('simulate.html',sidebar=nav('admin'),enabled=q("SELECT value FROM settings WHERE key='simulate'",one=True)['value']=='1')
@app.post(ADMIN_PATH+'/simulate/toggle')
@admin_required
def sim_toggle(): val='1' if q("SELECT value FROM settings WHERE key='simulate'",one=True)['value']!='1' else '0'; db().execute("UPDATE settings SET value=? WHERE key='simulate'",(val,)); db().commit(); return redirect(url_for('simulate'))

@app.get(ADMIN_PATH+'/system')
@admin_required
def admin_system():
 errors=[]
 return render_template('admin_system.html',sidebar=nav('admin'),errors=errors,db_path=DB)

@app.errorhandler(404)
def not_found(e):
 if request.path.startswith('/api/'): return jsonify(ok=False,error='not_found'),404
 return render_template('error.html',sidebar=nav(),code=404,message='That page does not exist.'),404
@app.errorhandler(403)
def forbidden(e): return render_template('error.html',sidebar=nav(),code=403,message='You do not have access to this area.'),403

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT','10000')))
