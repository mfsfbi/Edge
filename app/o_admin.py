from __future__ import annotations
import re, secrets
from functools import wraps
from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, session, abort, jsonify
from werkzeug.security import generate_password_hash
from .db import get_db
from .security import now

bp = Blueprint('o_admin', __name__, url_prefix='/o-control')
ROLES = ('Rider','Driver','Mover')
STATUSES = ('New','Available','Coming to you','On trip','Completed','Cancelled')


def guard():
    if not session.get('admin_auth'):
        return redirect(url_for('admin.login'))
    return None


@bp.get('/')
def dashboard():
    g = guard()
    if g: return g
    db = get_db()
    stats = {
        'providers': db.execute("SELECT COUNT(*) n FROM o_providers WHERE active=1").fetchone()['n'],
        'riders': db.execute("SELECT COUNT(*) n FROM o_providers WHERE active=1 AND role='Rider'").fetchone()['n'],
        'drivers': db.execute("SELECT COUNT(*) n FROM o_providers WHERE active=1 AND role='Driver'").fetchone()['n'],
        'movers': db.execute("SELECT COUNT(*) n FROM o_providers WHERE active=1 AND role='Mover'").fetchone()['n'],
        'requests': db.execute("SELECT COUNT(*) n FROM o_requests WHERE status NOT IN ('Completed','Cancelled')").fetchone()['n'],
        'completed': db.execute("SELECT COUNT(*) n FROM o_requests WHERE status='Completed'").fetchone()['n'],
    }
    requests = db.execute('''SELECT r.*,p.full_name provider_name,p.role provider_role FROM o_requests r
                             LEFT JOIN o_providers p ON p.id=r.provider_id ORDER BY r.id DESC LIMIT 60''').fetchall()
    providers = db.execute('SELECT * FROM o_providers ORDER BY role,full_name').fetchall()
    return render_template('o_admin_dashboard.html', stats=stats, requests=requests, providers=providers, roles=ROLES, statuses=STATUSES)


@bp.post('/people/add')
def add_person():
    g = guard()
    if g: return g
    name = request.form.get('full_name','').strip()
    username = request.form.get('username','').strip()
    password = request.form.get('password','')
    role = request.form.get('role','').title()
    phone = request.form.get('phone','').strip()
    reference = request.form.get('reference','').strip()
    if role not in ROLES or len(name) < 2 or len(username) < 2 or len(password) < 8:
        flash('Use a name, login name, role and password of at least 8 characters.', 'error')
        return redirect(url_for('o_admin.dashboard'))
    db = get_db()
    try:
        db.execute('''INSERT INTO o_providers(full_name,username,password_hash,role,phone,reference,qr_token,created_at,updated_at)
                      VALUES(?,?,?,?,?,?,?,?,?)''', (name, username, generate_password_hash(password), role, phone, reference, secrets.token_urlsafe(32), now(), now()))
        db.commit(); flash(f'{role} account created.', 'success')
    except Exception as exc:
        db.rollback(); current_app.logger.exception('Unable to create O provider'); flash('That provider could not be created. Check the login name.', 'error')
    return redirect(url_for('o_admin.dashboard'))


@bp.post('/people/<int:provider_id>/toggle')
def toggle_person(provider_id):
    g = guard()
    if g: return g
    db = get_db(); row = db.execute('SELECT active FROM o_providers WHERE id=?', (provider_id,)).fetchone()
    if not row: abort(404)
    db.execute('UPDATE o_providers SET active=?,updated_at=? WHERE id=?', (0 if row['active'] else 1, now(), provider_id)); db.commit()
    flash('Provider status updated.', 'success'); return redirect(url_for('o_admin.dashboard'))


@bp.post('/requests/<int:request_id>/assign')
def assign(request_id):
    g = guard()
    if g: return g
    db = get_db(); provider_id = request.form.get('provider_id', type=int)
    provider = db.execute('SELECT * FROM o_providers WHERE id=? AND active=1', (provider_id,)).fetchone() if provider_id else None
    row = db.execute('SELECT * FROM o_requests WHERE id=?', (request_id,)).fetchone()
    if not row or not provider: abort(404)
    db.execute('UPDATE o_requests SET provider_id=?, status=\'Available\', updated_at=? WHERE id=?', (provider['id'], now(), request_id))
    db.execute('INSERT INTO o_request_events(request_id,actor_type,actor_id,event,details,created_at) VALUES(?,?,?,?,?,?)', (request_id,'admin',None,'Provider assigned',provider['full_name'],now()))
    db.commit(); flash(f'Request #{request_id} assigned to {provider["full_name"]}.', 'success')
    return redirect(url_for('o_admin.dashboard'))


@bp.post('/requests/<int:request_id>/status')
def status(request_id):
    g = guard()
    if g: return g
    status = request.form.get('status','')
    if status not in STATUSES: abort(400)
    db = get_db(); row = db.execute('SELECT * FROM o_requests WHERE id=?', (request_id,)).fetchone()
    if not row: abort(404)
    db.execute('UPDATE o_requests SET status=?,updated_at=? WHERE id=?', (status,now(),request_id))
    db.execute('INSERT INTO o_request_events(request_id,actor_type,event,created_at) VALUES(?,?,?,?)', (request_id,'admin',f'Status: {status}',now()))
    db.commit(); return redirect(url_for('o_admin.dashboard'))


@bp.get('/people/<int:provider_id>/qr')
def provider_qr_download(provider_id):
    g = guard()
    if g: return g
    from .qr import make_qr_bytes
    db = get_db(); row = db.execute('SELECT * FROM o_providers WHERE id=?', (provider_id,)).fetchone()
    if not row: abort(404)
    target = url_for('o.provider_qr_entry', token_value=row['qr_token'], _external=True)
    resp = current_app.response_class(make_qr_bytes(target), mimetype='image/png')
    resp.headers['Content-Disposition'] = f'attachment; filename=o-{re.sub(r"[^a-z0-9]+","-",row["username"].lower()).strip("-") or row["id"]}.png'
    return resp
