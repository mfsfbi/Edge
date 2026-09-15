from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from pathlib import Path
import sqlite3, os, re

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get('DATA_DIR', '/var/data' if os.environ.get('RENDER') else str(BASE / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / 'o.db'

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-only-change-this-secret'),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=bool(os.environ.get('RENDER')),
)

PEOPLE_ROLES = ('Rider', 'Driver', 'Mover')
ROLE_DASHBOARDS = {'Rider': 'rider_dashboard', 'Driver': 'driver_dashboard', 'Mover': 'mover_dashboard'}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('Rider','Driver','Mover')),
            phone TEXT DEFAULT '',
            id_number TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(full_name, role)
        );
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER,
            service TEXT NOT NULL,
            destination TEXT DEFAULT '',
            pickup TEXT DEFAULT '',
            payment_method TEXT DEFAULT 'Cash',
            request_name TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE SET NULL
        );
        ''')
        c.commit()


def admin_ok():
    return session.get('admin_ok') is True


def person():
    pid = session.get('person_id')
    if not pid:
        return None
    with db() as c:
        return c.execute('SELECT * FROM people WHERE id=? AND active=1', (pid,)).fetchone()


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not admin_ok():
            return redirect(url_for('admin_login', next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def person_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not person():
            return redirect(url_for('people_login', role=request.args.get('role', '')))
        return fn(*args, **kwargs)
    return wrapper


def clean(s, limit=255):
    return re.sub(r'\s+', ' ', (s or '').strip())[:limit]


@app.route('/health')
def health():
    return {'ok': True, 'app': 'O', 'version': 'people-v1'}


@app.route('/')
def home():
    return render_template('home.html')


@app.route('/services')
def services():
    return render_template('services.html')


@app.route('/people', methods=['GET'])
def people():
    return render_template('people.html', roles=PEOPLE_ROLES)


@app.route('/people/<role>', methods=['GET'])
def people_role(role):
    if role not in PEOPLE_ROLES:
        abort(404)
    return redirect(url_for('people_login', role=role))


@app.route('/people/login', methods=['GET', 'POST'])
def people_login():
    role = clean(request.args.get('role') or request.form.get('role'))
    if role not in PEOPLE_ROLES:
        role = ''
    if request.method == 'POST':
        identity = clean(request.form.get('identity'), 255)
        password = request.form.get('password', '')
        selected = clean(request.form.get('role'), 30)
        if selected not in PEOPLE_ROLES or not identity or not password:
            flash('Choose your O role and enter the name and password used for your account.', 'error')
            return render_template('people_login.html', role=selected if selected in PEOPLE_ROLES else '')
        with db() as c:
            candidates = c.execute(
                '''SELECT * FROM people WHERE active=1 AND role=? AND (full_name=? OR phone=? OR id_number=?) LIMIT 2''',
                (selected, identity, identity, identity),
            ).fetchall()
        if len(candidates) == 1 and check_password_hash(candidates[0]['password_hash'], password):
            session.clear()
            session.permanent = True
            session['person_id'] = candidates[0]['id']
            return redirect(url_for(ROLE_DASHBOARDS[selected]))
        flash('That name, phone/ID and password did not match an active O account.', 'error')
    return render_template('people_login.html', role=role)


@app.route('/people/logout')
def people_logout():
    session.pop('person_id', None)
    return redirect(url_for('people'))


@app.route('/rider-dashboard')
@person_required
def rider_dashboard():
    p = person()
    if p['role'] != 'Rider': abort(403)
    return render_template('dashboard.html', person=p, title='Rider dashboard', accent='rider', body='Request a ride, check your current trip and keep moving with O.')


@app.route('/driver-dashboard')
@person_required
def driver_dashboard():
    p = person()
    if p['role'] != 'Driver': abort(403)
    return render_template('dashboard.html', person=p, title='Driver dashboard', accent='driver', body='Manage your O-Drive work, active requests and trips from one place.')


@app.route('/mover-dashboard')
@person_required
def mover_dashboard():
    p = person()
    if p['role'] != 'Mover': abort(403)
    return render_template('dashboard.html', person=p, title='Mover dashboard', accent='mover', body='Manage O-Movers requests and delivery work from one place.')


@app.route('/request', methods=['POST'])
def request_service():
    service = clean(request.form.get('service'), 30)
    destination = clean(request.form.get('destination'), 500)
    pickup = clean(request.form.get('pickup'), 500)
    payment_method = clean(request.form.get('payment_method'), 30) or 'Cash'
    request_name = clean(request.form.get('request_name'), 120)
    if service not in ('O-Ride', 'O-Drive', 'O-Movers'):
        flash('Choose an O service first.', 'error')
        return redirect(url_for('home'))
    p = person()
    with db() as c:
        c.execute('INSERT INTO requests(person_id,service,destination,pickup,payment_method,request_name) VALUES(?,?,?,?,?,?)',
                  (p['id'] if p else None, service, destination, pickup, payment_method, request_name))
        c.commit()
    flash('Your request was received.', 'success')
    return redirect(url_for('home'))


@app.route('/promise212324', methods=['GET', 'POST'])
def admin_login():
    if admin_ok():
        return redirect(url_for('admin_people'))
    if request.method == 'POST':
        username = clean(request.form.get('username'), 120)
        password = request.form.get('password', '')
        configured_user = os.environ.get('USER_NAME', 'admin')
        configured_password = os.environ.get('PASSWORD', '')
        if username == configured_user and configured_password and password == configured_password:
            session.clear(); session['admin_ok'] = True; session.permanent = True
            return redirect(request.args.get('next') or url_for('admin_people'))
        flash('Invalid control-room credentials.', 'error')
    return render_template('admin_login.html')


@app.route('/promise212324/logout')
def admin_logout():
    session.pop('admin_ok', None)
    return redirect(url_for('home'))


@app.route('/promise212324/people', methods=['GET', 'POST'])
@admin_required
def admin_people():
    if request.method == 'POST':
        full_name = clean(request.form.get('full_name'))
        password = request.form.get('password', '')
        role = clean(request.form.get('role'), 30)
        phone = clean(request.form.get('phone'), 50)
        id_number = clean(request.form.get('id_number'), 80)
        if not full_name or not password or role not in PEOPLE_ROLES:
            flash('Name, password and one O role are required.', 'error')
            return redirect(url_for('admin_people'))
        with db() as c:
            try:
                c.execute('INSERT INTO people(full_name,password_hash,role,phone,id_number) VALUES(?,?,?,?,?)',
                          (full_name, generate_password_hash(password), role, phone, id_number))
                c.commit()
            except sqlite3.IntegrityError:
                flash('That name already exists for the selected O role.', 'error')
                return redirect(url_for('admin_people'))
        flash(f'{full_name} was added as {role}. They can now use the same name and password at /people.', 'success')
        return redirect(url_for('admin_people'))
    with db() as c:
        people_rows = c.execute('SELECT id,full_name,role,phone,id_number,active,created_at FROM people ORDER BY role,full_name').fetchall()
    return render_template('admin_people.html', people=people_rows)


@app.post('/promise212324/people/<int:person_id>/toggle')
@admin_required
def admin_people_toggle(person_id):
    with db() as c:
        c.execute('UPDATE people SET active=CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=?', (person_id,)); c.commit()
    return redirect(url_for('admin_people'))


@app.post('/promise212324/people/<int:person_id>/delete')
@admin_required
def admin_people_delete(person_id):
    with db() as c:
        c.execute('DELETE FROM people WHERE id=?', (person_id,)); c.commit()
    return redirect(url_for('admin_people'))


@app.route('/promise212324/requests')
@admin_required
def admin_requests():
    with db() as c:
        rows = c.execute('''SELECT r.*, p.full_name FROM requests r LEFT JOIN people p ON p.id=r.person_id ORDER BY r.id DESC LIMIT 100''').fetchall()
    return render_template('admin_requests.html', requests=rows)


@app.errorhandler(403)
def forbidden(_):
    return render_template('error.html', code=403, message='You do not have access to this area.'), 403


@app.errorhandler(404)
def not_found(_):
    return render_template('error.html', code=404, message='That O page does not exist.'), 404


init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8000')))
