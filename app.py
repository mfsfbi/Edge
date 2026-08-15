from flask import Flask, render_template, request, redirect, url_for, jsonify
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError
from bson import ObjectId
from bson.errors import InvalidId
import os
import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tthms-prototype-local')

MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://127.0.0.1:27017')
MONGO_DB = os.environ.get('MONGO_DB', 'tthms')

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
db = client[MONGO_DB]
patients_col = db.patients
events_col = db.events
appointments_col = db.appointments
bills_col = db.bills
inventory_col = db.inventory

MODULES = [
    ('Dashboard','dashboard','fa-house'), ('Reception','reception','fa-desktop'),
    ('Appointments','appointments','fa-calendar-check'), ('Patients','patients','fa-user-injured'),
    ('Consultations','consultations','fa-stethoscope'), ('Laboratory','laboratory','fa-flask'),
    ('Pharmacy','pharmacy','fa-pills'), ('Admissions','admissions','fa-bed'),
    ('Billing','billing','fa-file-invoice-dollar'), ('Inventory','inventory','fa-boxes-stacked'),
    ('Reports','reports','fa-chart-line'), ('AI Assistant','ai_assistant','fa-wand-magic-sparkles'),
    ('Backups','backups','fa-database'), ('Administration','administration','fa-gear')
]


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def oid(value):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def doc_out(doc):
    if not doc:
        return doc
    x = dict(doc)
    if '_id' in x:
        x['_id'] = str(x['_id'])
    if 'patient_id' in x and isinstance(x['patient_id'], ObjectId):
        x['patient_id'] = str(x['patient_id'])
    return x


def ensure_mongo():
    try:
        client.admin.command('ping')
    except ServerSelectionTimeoutError as exc:
        raise RuntimeError(
            'MongoDB is not reachable. Start MongoDB locally or set MONGO_URI to a reachable MongoDB/Atlas connection string.'
        ) from exc


def init_db():
    ensure_mongo()
    patients_col.create_index([('patient_no', ASCENDING)], unique=True)
    patients_col.create_index([('name', ASCENDING)])
    events_col.create_index([('patient_id', ASCENDING), ('created_at', DESCENDING)])
    appointments_col.create_index([('appointment_date', ASCENDING)])
    bills_col.create_index([('patient_id', ASCENDING), ('created_at', DESCENDING)])
    inventory_col.create_index([('item', ASCENDING)])

    if patients_col.count_documents({}) == 0:
        created = now_iso()
        seed = [
            {'patient_no':'TTH-0001','name':'Amina Hassan','sex':'F','age':31,'phone':'0712345678','blood_group':'O+','allergies':'Penicillin','status':'Active','created_at':created},
            {'patient_no':'TTH-0002','name':'Brian Otieno','sex':'M','age':44,'phone':'0723456789','blood_group':'A+','allergies':'None known','status':'Active','created_at':created},
            {'patient_no':'TTH-0003','name':'Faith Wanjiku','sex':'F','age':19,'phone':'0734567890','blood_group':'B+','allergies':'None known','status':'Active','created_at':created},
        ]
        result = patients_col.insert_many(seed)
        pids = result.inserted_ids
        event_seed = [
            (pids[0], 'Registration', 'Patient registered', 'Patient registered at reception.'),
            (pids[0], 'Consultation', 'Routine consultation', 'Routine outpatient consultation.'),
            (pids[0], 'Prescription', 'Prescription issued', 'Prescription issued for clinician review.'),
            (pids[1], 'Registration', 'Patient registered', 'Patient registered at reception.'),
            (pids[1], 'Lab request', 'CBC and chemistry', 'CBC and chemistry requested.'),
        ]
        events_col.insert_many([
            {'patient_id': pid, 'event_type': et, 'title': title, 'detail': detail, 'created_at': created}
            for pid, et, title, detail in event_seed
        ])
        inventory_col.insert_many([
            {'item':'Paracetamol 500mg','category':'Pharmacy','quantity':420,'reorder_level':100,'unit_cost':2.50},
            {'item':'Amoxicillin 500mg','category':'Pharmacy','quantity':85,'reorder_level':100,'unit_cost':8.00},
            {'item':'IV Normal Saline 500ml','category':'Consumables','quantity':62,'reorder_level':30,'unit_cost':145.00},
            {'item':'Gloves Medium','category':'Consumables','quantity':900,'reorder_level':300,'unit_cost':8.50}
        ])


# MongoDB is required for this build. The application still starts with `python app.py`
# provided MongoDB is running locally or MONGO_URI points to MongoDB Atlas/another server.
try:
    init_db()
    MONGO_STARTUP_ERROR = None
except RuntimeError as exc:
    MONGO_STARTUP_ERROR = str(exc)


def page(title, **ctx):
    return render_template('page.html', title=title, modules=MODULES, **ctx)


@app.route('/')
def index():
    return redirect(url_for('dashboard'))


@app.route('/dashboard')
def dashboard():
    counts = {
        'patients': patients_col.count_documents({}),
        'appointments': appointments_col.count_documents({'status': 'Scheduled'}),
        'pending_bills': sum(float(x.get('amount', 0) or 0) for x in bills_col.find({'status': 'Pending'}, {'amount': 1})),
        'low_stock': inventory_col.count_documents({'$expr': {'$lte': ['$quantity', '$reorder_level']}}),
    }
    recent = []
    for e in events_col.find().sort('_id', DESCENDING).limit(8):
        p = patients_col.find_one({'_id': e.get('patient_id')}, {'name': 1, 'patient_no': 1})
        e = doc_out(e)
        e['name'] = p.get('name') if p else 'Unknown'
        e['patient_no'] = p.get('patient_no') if p else '—'
        recent.append(e)
    return page('Dashboard', active='dashboard', counts=counts, recent=recent)


@app.route('/reception', methods=['GET','POST'])
def reception():
    message = None
    if request.method == 'POST':
        f = request.form
        patient = {
            'patient_no': f['patient_no'], 'name': f['name'], 'sex': f.get('sex'),
            'age': int(f['age']) if f.get('age') else None, 'phone': f.get('phone'),
            'blood_group': f.get('blood_group'), 'allergies': f.get('allergies'),
            'status': 'Active', 'created_at': now_iso()
        }
        try:
            cur = patients_col.insert_one(patient)
            events_col.insert_one({'patient_id': cur.inserted_id, 'event_type':'Registration', 'title':'Patient registered', 'detail':'Registration completed at reception.', 'created_at':now_iso()})
            message = 'Patient registered successfully.'
        except DuplicateKeyError:
            message = 'Patient number already exists.'
    return page('Reception', active='reception', message=message)


@app.route('/patients')
def patients():
    q = request.args.get('q', '').strip()
    if q:
        rows = list(patients_col.find({'$or': [{'name': {'$regex': q, '$options': 'i'}}, {'patient_no': {'$regex': q, '$options': 'i'}}]}).sort('_id', DESCENDING))
    else:
        rows = list(patients_col.find().sort('_id', DESCENDING))
    return page('Patients', active='patients', patients=[doc_out(x) for x in rows], q=q)


@app.route('/patients/<pid>')
def patient(pid):
    p_id = oid(pid)
    if not p_id:
        return ('Patient not found', 404)
    p = patients_col.find_one({'_id': p_id})
    if not p:
        return ('Patient not found', 404)
    events = [doc_out(x) for x in events_col.find({'patient_id': p_id}).sort('_id', DESCENDING)]
    bills = [doc_out(x) for x in bills_col.find({'patient_id': p_id}).sort('_id', DESCENDING)]
    return page('Patient Profile', active='patients', patient=doc_out(p), events=events, bills=bills)


@app.route('/consultations')
def consultations():
    rows = [doc_out(x) for x in patients_col.find().sort('name', ASCENDING)]
    return page('Consultations', active='consultations', patients=rows)


@app.route('/consultations/<pid>', methods=['GET','POST'])
def consultation(pid):
    p_id = oid(pid)
    if not p_id:
        return ('Patient not found', 404)
    p = patients_col.find_one({'_id': p_id})
    if not p:
        return ('Patient not found', 404)
    if request.method == 'POST':
        events_col.insert_one({'patient_id':p_id, 'event_type':'Consultation', 'title':request.form.get('title','Consultation'), 'detail':request.form.get('notes',''), 'created_at':now_iso()})
        return redirect(url_for('patient', pid=str(p_id)))
    history = [doc_out(x) for x in events_col.find({'patient_id': p_id}).sort('_id', DESCENDING)]
    return page('Consultation', active='consultations', patient=doc_out(p), history=history)


@app.route('/appointments')
def appointments():
    rows = []
    for a in appointments_col.find().sort('appointment_date', ASCENDING):
        a = doc_out(a); p = patients_col.find_one({'_id': a.get('patient_id')}, {'name':1,'patient_no':1})
        a['name'] = p.get('name') if p else 'Unknown'; a['patient_no'] = p.get('patient_no') if p else '—'; rows.append(a)
    patients = [doc_out(x) for x in patients_col.find().sort('name', ASCENDING)]
    return page('Appointments', active='appointments', appointments=rows, patients=patients)


@app.route('/appointments/add', methods=['POST'])
def appointments_add():
    appointments_col.insert_one({'patient_id': oid(request.form['patient_id']), 'appointment_date': request.form['appointment_date'], 'doctor': request.form['doctor'], 'reason': request.form['reason'], 'status': 'Scheduled'})
    return redirect(url_for('appointments'))


@app.route('/pharmacy')
def pharmacy():
    stock = [doc_out(x) for x in inventory_col.find({'category':'Pharmacy'}).sort('item', ASCENDING)]
    return page('Pharmacy', active='pharmacy', stock=stock)


@app.route('/laboratory')
def laboratory():
    return page('Laboratory', active='laboratory', tests=['CBC','U&E','Liver Function','Malaria Screen','Urinalysis','Blood Group','Pregnancy Test'])


@app.route('/admissions')
def admissions():
    return page('Admissions', active='admissions', beds=[('Ward A',12,8),('Ward B',10,4),('Maternity',8,6),('Pediatric',10,7)])


@app.route('/billing')
def billing():
    rows=[]
    for b in bills_col.find().sort('_id', DESCENDING):
        b=doc_out(b); p=patients_col.find_one({'_id': b.get('patient_id')}, {'name':1,'patient_no':1})
        b['name']=p.get('name') if p else 'Unknown'; b['patient_no']=p.get('patient_no') if p else '—'; rows.append(b)
    patients=[doc_out(x) for x in patients_col.find().sort('name', ASCENDING)]
    return page('Billing', active='billing', bills=rows, patients=patients)


@app.route('/billing/add', methods=['POST'])
def billing_add():
    bills_col.insert_one({'patient_id':oid(request.form['patient_id']), 'description':request.form['description'], 'amount':float(request.form['amount']), 'status':'Pending', 'created_at':now_iso()})
    return redirect(url_for('billing'))


@app.route('/inventory')
def inventory():
    rows=[doc_out(x) for x in inventory_col.find().sort('item', ASCENDING)]
    return page('Inventory', active='inventory', inventory=rows)


@app.route('/reports')
def reports():
    return page('Reports', active='reports', report_types=['Daily Operations','Patient Activity','Billing Summary','Pharmacy Stock','Laboratory Activity','Admissions & Discharges','Audit Summary'])


@app.route('/ai-assistant')
def ai_assistant():
    return page('AI Assistant', active='ai_assistant')


@app.route('/backups')
def backups():
    # MongoDB backups are handled through mongodump/Atlas snapshots in production.
    return page('Backups', active='backups', backup_file='MongoDB database: ' + MONGO_DB, backup_time='Use mongodump or MongoDB Atlas backups')


@app.route('/administration')
def administration():
    return page('Administration', active='administration')


@app.route('/api/patient/<pid>')
def api_patient(pid):
    p_id = oid(pid)
    if not p_id:
        return jsonify({'error':'not found'}),404
    p = patients_col.find_one({'_id': p_id})
    if not p:
        return jsonify({'error':'not found'}),404
    e = [doc_out(x) for x in events_col.find({'patient_id': p_id}).sort('_id', DESCENDING)]
    return jsonify({'patient':doc_out(p),'timeline':e})


@app.route('/health')
def health():
    try:
        client.admin.command('ping')
        return jsonify({'status':'ok','mongodb':'connected','database':MONGO_DB})
    except Exception as exc:
        return jsonify({'status':'error','mongodb':'unreachable','detail':str(exc)}), 503


@app.route('/sw.js')
def sw():
    response = app.send_static_file('sw.js')
    response.headers['Content-Type'] = 'application/javascript'
    return response


if __name__ == '__main__':
    if MONGO_STARTUP_ERROR:
        raise SystemExit('\nTTHMS startup failed:\n' + MONGO_STARTUP_ERROR + '\n')
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
