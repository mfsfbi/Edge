from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3, os, datetime

BASE = os.path.dirname(__file__)
DB = os.path.join(BASE, 'instance', 'tthms.db')
app = Flask(__name__)
app.config['SECRET_KEY'] = 'tthms-prototype-local'

MODULES = [
    ('Dashboard','dashboard','fa-house'), ('Reception','reception','fa-desktop'),
    ('Appointments','appointments','fa-calendar-check'), ('Patients','patients','fa-user-injured'),
    ('Consultations','consultations','fa-stethoscope'), ('Laboratory','laboratory','fa-flask'),
    ('Pharmacy','pharmacy','fa-pills'), ('Admissions','admissions','fa-bed'),
    ('Billing','billing','fa-file-invoice-dollar'), ('Inventory','inventory','fa-boxes-stacked'),
    ('Reports','reports','fa-chart-line'), ('AI Assistant','ai_assistant','fa-wand-magic-sparkles'),
    ('Backups','backups','fa-database'), ('Administration','administration','fa-gear')
]

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = db()
    con.executescript('''
    CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_no TEXT UNIQUE,
        name TEXT NOT NULL,
        sex TEXT,
        age INTEGER,
        phone TEXT,
        blood_group TEXT,
        allergies TEXT,
        status TEXT DEFAULT 'Active',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        event_type TEXT NOT NULL,
        title TEXT NOT NULL,
        detail TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(patient_id) REFERENCES patients(id)
    );
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        appointment_date TEXT,
        doctor TEXT,
        reason TEXT,
        status TEXT DEFAULT 'Scheduled'
    );
    CREATE TABLE IF NOT EXISTS bills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        description TEXT,
        amount REAL,
        status TEXT DEFAULT 'Pending',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item TEXT,
        category TEXT,
        quantity INTEGER,
        reorder_level INTEGER,
        unit_cost REAL
    );
    ''')
    if con.execute('SELECT COUNT(*) FROM patients').fetchone()[0] == 0:
        now = datetime.datetime.now().isoformat(timespec='seconds')
        seed = [
            ('TTH-0001','Amina Hassan','F',31,'0712345678','O+','Penicillin','Active'),
            ('TTH-0002','Brian Otieno','M',44,'0723456789','A+','None known','Active'),
            ('TTH-0003','Faith Wanjiku','F',19,'0734567890','B+','None known','Active'),
        ]
        con.executemany('INSERT INTO patients(patient_no,name,sex,age,phone,blood_group,allergies,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                        [(*row, now) for row in seed])
        pids = [r[0] for r in con.execute('SELECT id FROM patients ORDER BY id').fetchall()]
        for pid, title, detail in [
            (pids[0], 'Registration', 'Patient registered at reception.'),
            (pids[0], 'Consultation', 'Routine outpatient consultation.'),
            (pids[0], 'Prescription', 'Prescription issued for clinician review.'),
            (pids[1], 'Registration', 'Patient registered at reception.'),
            (pids[1], 'Lab request', 'CBC and chemistry requested.'),
        ]:
            con.execute('INSERT INTO events(patient_id,event_type,title,detail,created_at) VALUES(?,?,?,?,?)',
                        (pid, title, title, detail, now))
        con.executemany('INSERT INTO inventory(item,category,quantity,reorder_level,unit_cost) VALUES(?,?,?,?,?)', [
            ('Paracetamol 500mg','Pharmacy',420,100,2.50), ('Amoxicillin 500mg','Pharmacy',85,100,8.00),
            ('IV Normal Saline 500ml','Consumables',62,30,145.00), ('Gloves Medium','Consumables',900,300,8.50)
        ])
    con.commit(); con.close()

init_db()

def page(title, **ctx):
    return render_template('page.html', title=title, modules=MODULES, **ctx)

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    con=db();
    counts={
        'patients': con.execute('SELECT COUNT(*) FROM patients').fetchone()[0],
        'appointments': con.execute("SELECT COUNT(*) FROM appointments WHERE status='Scheduled'").fetchone()[0],
        'pending_bills': con.execute("SELECT COALESCE(SUM(amount),0) FROM bills WHERE status='Pending'").fetchone()[0],
        'low_stock': con.execute('SELECT COUNT(*) FROM inventory WHERE quantity <= reorder_level').fetchone()[0],
    }
    recent=con.execute('''SELECT e.*, p.name, p.patient_no FROM events e JOIN patients p ON p.id=e.patient_id ORDER BY e.id DESC LIMIT 8''').fetchall(); con.close()
    return page('Dashboard', active='dashboard', counts=counts, recent=recent)

@app.route('/reception', methods=['GET','POST'])
def reception():
    message=None
    if request.method=='POST':
        f=request.form; con=db(); now=datetime.datetime.now().isoformat(timespec='seconds')
        try:
            cur=con.execute('INSERT INTO patients(patient_no,name,sex,age,phone,blood_group,allergies,created_at) VALUES(?,?,?,?,?,?,?,?)',
                            (f['patient_no'],f['name'],f.get('sex'),f.get('age') or None,f.get('phone'),f.get('blood_group'),f.get('allergies'),now))
            con.execute('INSERT INTO events(patient_id,event_type,title,detail,created_at) VALUES(?,?,?,?,?)',(cur.lastrowid,'Registration','Patient registered','Registration completed at reception.',now)); con.commit(); message='Patient registered successfully.'
        except sqlite3.IntegrityError: message='Patient number already exists.'
        finally: con.close()
    return page('Reception', active='reception', message=message)

@app.route('/patients')
def patients():
    q=request.args.get('q','').strip(); con=db()
    if q:
        rows=con.execute('SELECT * FROM patients WHERE name LIKE ? OR patient_no LIKE ? ORDER BY id DESC', (f'%{q}%',f'%{q}%')).fetchall()
    else: rows=con.execute('SELECT * FROM patients ORDER BY id DESC').fetchall()
    con.close(); return page('Patients', active='patients', patients=rows, q=q)

@app.route('/patients/<int:pid>')
def patient(pid):
    con=db(); p=con.execute('SELECT * FROM patients WHERE id=?',(pid,)).fetchone(); events=con.execute('SELECT * FROM events WHERE patient_id=? ORDER BY id DESC',(pid,)).fetchall(); bills=con.execute('SELECT * FROM bills WHERE patient_id=? ORDER BY id DESC',(pid,)).fetchall(); con.close()
    if not p: return ('Patient not found',404)
    return page('Patient Profile', active='patients', patient=p, events=events, bills=bills)

@app.route('/consultations')
def consultations():
    con=db(); rows=con.execute('SELECT * FROM patients ORDER BY name').fetchall(); con.close(); return page('Consultations', active='consultations', patients=rows)

@app.route('/consultations/<int:pid>', methods=['GET','POST'])
def consultation(pid):
    con=db(); p=con.execute('SELECT * FROM patients WHERE id=?',(pid,)).fetchone()
    if not p: con.close(); return ('Patient not found',404)
    if request.method=='POST':
        now=datetime.datetime.now().isoformat(timespec='seconds'); title=request.form.get('title','Consultation'); detail=request.form.get('notes','')
        con.execute('INSERT INTO events(patient_id,event_type,title,detail,created_at) VALUES(?,?,?,?,?)',(pid,'Consultation',title,detail,now));
        con.commit(); con.close(); return redirect(url_for('patient',pid=pid))
    history=con.execute('SELECT * FROM events WHERE patient_id=? ORDER BY id DESC',(pid,)).fetchall(); con.close(); return page('Consultation', active='consultations', patient=p, history=history)

@app.route('/appointments')
def appointments():
    con=db(); rows=con.execute('SELECT a.*,p.name,p.patient_no FROM appointments a JOIN patients p ON p.id=a.patient_id ORDER BY a.appointment_date').fetchall(); patients=con.execute('SELECT * FROM patients ORDER BY name').fetchall(); con.close(); return page('Appointments', active='appointments', appointments=rows, patients=patients)

@app.route('/appointments/add', methods=['POST'])
def appointments_add():
    con=db(); con.execute('INSERT INTO appointments(patient_id,appointment_date,doctor,reason) VALUES(?,?,?,?)',(request.form['patient_id'],request.form['appointment_date'],request.form['doctor'],request.form['reason'])); con.commit(); con.close(); return redirect(url_for('appointments'))

@app.route('/pharmacy')
def pharmacy():
    con=db(); stock=con.execute('SELECT * FROM inventory WHERE category="Pharmacy" ORDER BY item').fetchall(); con.close(); return page('Pharmacy', active='pharmacy', stock=stock)

@app.route('/laboratory')
def laboratory(): return page('Laboratory', active='laboratory', tests=['CBC','U&E','Liver Function','Malaria Screen','Urinalysis','Blood Group','Pregnancy Test'])
@app.route('/admissions')
def admissions(): return page('Admissions', active='admissions', beds=[('Ward A',12,8),('Ward B',10,4),('Maternity',8,6),('Pediatric',10,7)])

@app.route('/billing')
def billing():
    con=db(); bills=con.execute('SELECT b.*,p.name,p.patient_no FROM bills b JOIN patients p ON p.id=b.patient_id ORDER BY b.id DESC').fetchall(); patients=con.execute('SELECT * FROM patients ORDER BY name').fetchall(); con.close(); return page('Billing', active='billing', bills=bills, patients=patients)

@app.route('/billing/add', methods=['POST'])
def billing_add():
    con=db(); con.execute('INSERT INTO bills(patient_id,description,amount,created_at) VALUES(?,?,?,?)',(request.form['patient_id'],request.form['description'],request.form['amount'],datetime.datetime.now().isoformat(timespec='seconds'))); con.commit(); con.close(); return redirect(url_for('billing'))

@app.route('/inventory')
def inventory():
    con=db(); rows=con.execute('SELECT * FROM inventory ORDER BY item').fetchall(); con.close(); return page('Inventory', active='inventory', inventory=rows)
@app.route('/reports')
def reports(): return page('Reports', active='reports', report_types=['Daily Operations','Patient Activity','Billing Summary','Pharmacy Stock','Laboratory Activity','Admissions & Discharges','Audit Summary'])
@app.route('/ai-assistant')
def ai_assistant(): return page('AI Assistant', active='ai_assistant')
@app.route('/backups')
def backups(): return page('Backups', active='backups', backup_file=os.path.basename(DB), backup_time=datetime.datetime.fromtimestamp(os.path.getmtime(DB)).isoformat(timespec='seconds'))
@app.route('/administration')
def administration(): return page('Administration', active='administration')

@app.route('/api/patient/<int:pid>')
def api_patient(pid):
    con=db(); p=con.execute('SELECT * FROM patients WHERE id=?',(pid,)).fetchone(); e=con.execute('SELECT * FROM events WHERE patient_id=? ORDER BY id DESC',(pid,)).fetchall(); con.close()
    if not p: return jsonify({'error':'not found'}),404
    return jsonify({'patient':dict(p),'timeline':[dict(x) for x in e]})

@app.route('/sw.js')
def sw(): return app.send_static_file('sw.js'), {'Content-Type':'application/javascript'}

if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)), debug=False)
