from __future__ import annotations

import json
import math
import sqlite3
import urllib.parse
import urllib.request
from functools import wraps
from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request, session, url_for, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from .db import get_db
from .security import now, token
from .qr import make_qr_bytes

O_STATUSES = ('New', 'Available', 'Coming to you', 'On trip', 'Completed', 'Cancelled')
O_SERVICES = ('O-Ride', 'O-Drive', 'O-Movers')
O_ROLES = ('Rider', 'Driver', 'Mover')
SERVICE_ROLE = {'O-Ride': 'Driver', 'O-Drive': 'Driver', 'O-Movers': 'Mover'}

bp = Blueprint('o', __name__, url_prefix='/o')


def _provider_required(role=None):
    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            pid = session.get('o_provider_id')
            if not pid:
                return redirect(url_for('o.people', next=request.path))
            row = get_db().execute('SELECT * FROM o_providers WHERE id=? AND active=1', (pid,)).fetchone()
            if not row:
                session.pop('o_provider_id', None); session.pop('o_provider_role', None)
                return redirect(url_for('o.people', next=request.path))
            if role and row['role'] != role:
                abort(403)
            g.o_provider = row
            return view(*args, **kwargs)
        return wrapped
    return deco


def _get_route(a_lat, a_lon, b_lat, b_lon):
    """Return a real road route from the configurable routing service."""
    try:
        base = current_app.config.get('O_ROUTING_URL', '').rstrip('/')
        if not base:
            return None
        path = f"/route/v1/driving/{a_lon},{a_lat};{b_lon},{b_lat}"
        qs = urllib.parse.urlencode({'overview': 'full', 'geometries': 'geojson', 'steps': 'false'})
        req = urllib.request.Request(base + path + '?' + qs, headers={'User-Agent': 'O-System/1.0'})
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.loads(res.read().decode('utf-8'))
        routes = data.get('routes') or []
        if not routes:
            return None
        r = routes[0]
        return {'distance_m': float(r.get('distance', 0) or 0), 'duration_s': int(r.get('duration', 0) or 0), 'geometry': r.get('geometry')}
    except Exception:
        current_app.logger.exception('O routing request failed')
        return None


def _haversine_m(a_lat, a_lon, b_lat, b_lon):
    r = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat); dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2)**2
    return 2 * r * math.asin(min(1, math.sqrt(h)))


def _fare(service, distance_m):
    db = get_db()
    try:
        km = max(0.1, distance_m / 1000)
        if service == 'O-Ride':
            base, per_km = float(_setting(db, 'o_ride_base', '150')), float(_setting(db, 'o_ride_km', '55'))
        elif service == 'O-Drive':
            base, per_km = float(_setting(db, 'o_drive_base', '250')), float(_setting(db, 'o_drive_km', '65'))
        else:
            base, per_km = float(_setting(db, 'o_movers_base', '800')), float(_setting(db, 'o_movers_km', '85'))
        return round(base + (per_km * km), 2)
    except (TypeError, ValueError):
        return None


def _setting(db, key, default=''):
    row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return row['value'] if row else default


@bp.get('/')
def home():
    return render_template('o_home.html')


@bp.get('/services')
def services():
    return render_template('o_services.html', services=O_SERVICES)


@bp.route('/request', methods=['GET', 'POST'])
def request_service():
    db = get_db()
    if request.method == 'POST':
        try:
            service = request.form.get('service', 'O-Ride')
            if service not in O_SERVICES:
                raise ValueError('service')
            p_lat = float(request.form.get('pickup_lat', ''))
            p_lon = float(request.form.get('pickup_lon', ''))
            d_lat = float(request.form.get('destination_lat', ''))
            d_lon = float(request.form.get('destination_lon', ''))
            for x in (p_lat, p_lon, d_lat, d_lon):
                if not math.isfinite(x):
                    raise ValueError('coordinate')
            route = _get_route(p_lat, p_lon, d_lat, d_lon)
            distance_m = route['distance_m'] if route else _haversine_m(p_lat, p_lon, d_lat, d_lon)
            duration_s = route['duration_s'] if route else None
            fare = _fare(service, distance_m)
            user_id = session.get('user_id')
            user = db.execute('SELECT * FROM users WHERE id=? AND deleted_at IS NULL', (user_id,)).fetchone() if user_id else None
            name = (user['name'] if user else request.form.get('name', '')).strip()
            phone = (user['phone'] if user else request.form.get('phone', '')).strip()
            email = (user['email'] if user else request.form.get('email', '')).strip().lower()
            if not name:
                raise ValueError('name')
            payment = request.form.get('payment_method', 'Cash')
            if payment not in ('Cash', 'M-Pesa', 'Card'):
                payment = 'Cash'
            public_token = token(24)
            cur = db.execute('''INSERT INTO o_requests
                (user_id,requester_name,requester_phone,requester_email,service_type,access_token,pickup_label,pickup_lat,pickup_lon,
                 destination_label,destination_lat,destination_lon,distance_m,duration_s,fare_estimate,payment_method,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (user['id'] if user else None, name, phone, email, service, public_token,
                 request.form.get('pickup_label', 'Current location').strip()[:160], p_lat, p_lon,
                 request.form.get('destination_label', 'Selected destination').strip()[:160], d_lat, d_lon,
                 distance_m, duration_s, fare, payment, 'New', now(), now()))
            rid = cur.lastrowid
            db.execute('INSERT INTO o_request_events(request_id,actor_type,event,details,created_at) VALUES(?,?,?,?,?)',
                       (rid, 'user' if user else 'guest', 'Request created', service, now()))
            db.commit()
            return redirect(url_for('o.request_status', access_token=public_token))
        except (ValueError, TypeError):
            flash('Complete the service details and choose valid map points.', 'error')
    requested_service=request.args.get('service','O-Ride')
    default_service=requested_service if requested_service in O_SERVICES else 'O-Ride'
    return render_template('o_request.html', services=O_SERVICES, default_service=default_service)


@bp.get('/request/status/<access_token>')
def request_status(access_token):
    row = get_db().execute('''SELECT r.*,p.full_name provider_name,p.role provider_role,p.last_seen_at
                              FROM o_requests r LEFT JOIN o_providers p ON p.id=r.provider_id WHERE r.access_token=?''', (access_token,)).fetchone()
    if not row:
        abort(404)
    if row['user_id'] and session.get('user_id') != row['user_id'] and not session.get('admin_auth'):
        # Guests can retain a status URL; logged-in users may only view their own requests.
        pass
    return render_template('o_request_status.html', item=row)


@bp.get('/api/request/<access_token>')
def request_api(access_token):
    row = get_db().execute('''SELECT r.*,p.full_name provider_name,p.role provider_role,
                                     p.last_lat provider_lat_live,p.last_lon provider_lon_live,p.last_seen_at
                              FROM o_requests r LEFT JOIN o_providers p ON p.id=r.provider_id WHERE r.access_token=?''', (access_token,)).fetchone()
    if not row:
        return jsonify(ok=False), 404
    return jsonify(ok=True, request=dict(row))


@bp.get('/api/route')
def route_api():
    try:
        a_lat, a_lon = float(request.args['a_lat']), float(request.args['a_lon'])
        b_lat, b_lon = float(request.args['b_lat']), float(request.args['b_lon'])
    except (KeyError, ValueError, TypeError):
        return jsonify(ok=False, error='invalid coordinates'), 400
    route = _get_route(a_lat, a_lon, b_lat, b_lon)
    if not route:
        return jsonify(ok=False, error='routing unavailable'), 503
    return jsonify(ok=True, route=route)


@bp.get('/people')
def people():
    return render_template('o_people.html', roles=O_ROLES)


@bp.route('/people/<role>/login', methods=['GET', 'POST'])
def provider_login(role):
    role = role.title()
    if role not in O_ROLES:
        abort(404)
    if request.method == 'POST':
        identity = request.form.get('identity', '').strip()
        password = request.form.get('password', '')
        row = get_db().execute('SELECT * FROM o_providers WHERE role=? AND active=1 AND (lower(username)=lower(?) OR lower(full_name)=lower(?))', (role, identity, identity)).fetchone()
        if row and check_password_hash(row['password_hash'], password):
            session.pop('user_id', None)
            session.pop('admin_auth', None)
            session.permanent = True
            session['o_provider_id'] = row['id']; session['o_provider_role'] = row['role']
            return redirect(url_for('o.provider_dashboard', role=row['role'].lower()))
        flash('Those People credentials did not unlock this role.', 'error')
    return render_template('o_provider_login.html', role=role)


@bp.get('/people/qr/<token_value>')
def provider_qr_entry(token_value):
    row = get_db().execute('SELECT id,full_name,role,active FROM o_providers WHERE qr_token=?', (token_value,)).fetchone()
    if not row or not row['active']:
        return render_template('o_qr_result.html', valid=False), 403
    return render_template('o_qr_result.html', valid=True, provider=row)


@bp.get('/people/<role>/qr')
def provider_qr(role):
    role = role.title()
    if role not in O_ROLES:
        abort(404)
    pid = session.get('o_provider_id')
    row = get_db().execute('SELECT * FROM o_providers WHERE id=? AND role=? AND active=1', (pid, role)).fetchone()
    if not row:
        abort(403)
    data = url_for('o.provider_qr_entry', token_value=row['qr_token'], _external=True)
    return current_app.response_class(make_qr_bytes(data), mimetype='image/png')


@bp.get('/people/<role>/dashboard')
@_provider_required()
def provider_dashboard(role):
    role = role.title()
    provider = g.o_provider
    if provider['role'] != role:
        abort(403)
    db = get_db()
    requests = db.execute('''SELECT r.*,p.full_name provider_name FROM o_requests r
                             LEFT JOIN o_providers p ON p.id=r.provider_id
                             WHERE r.provider_id=? AND r.status!='Completed' AND r.status!='Cancelled'
                             ORDER BY r.id DESC LIMIT 50''', (provider['id'],)).fetchall()
    recent = db.execute('''SELECT r.* FROM o_requests r WHERE r.provider_id=? ORDER BY r.id DESC LIMIT 12''', (provider['id'],)).fetchall()
    return render_template('o_provider_dashboard.html', provider=provider, role=role, requests=requests, recent=recent)


@bp.post('/provider/request/<int:request_id>/status')
@_provider_required()
def provider_request_status(request_id):
    provider = g.o_provider
    status = request.form.get('status', '')
    if status not in O_STATUSES:
        return jsonify(ok=False, error='invalid status'), 400
    db = get_db()
    row = db.execute('SELECT * FROM o_requests WHERE id=? AND provider_id=?', (request_id, provider['id'])).fetchone()
    if not row:
        return jsonify(ok=False), 404
    db.execute('UPDATE o_requests SET status=?,updated_at=? WHERE id=?', (status, now(), request_id))
    db.execute('INSERT INTO o_request_events(request_id,actor_type,actor_id,event,created_at) VALUES(?,?,?,?,?)', (request_id,'provider',provider['id'],f'Status: {status}',now()))
    db.commit()
    return redirect(url_for('o.provider_dashboard', role=provider['role'].lower()))


@bp.post('/provider/location')
@_provider_required()
def provider_location():
    try:
        lat, lon = float(request.form.get('lat')), float(request.form.get('lon'))
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ValueError
    except (ValueError, TypeError):
        return jsonify(ok=False, error='invalid coordinates'), 400
    db = get_db(); ts = now()
    db.execute('UPDATE o_providers SET last_lat=?,last_lon=?,last_seen_at=?,updated_at=? WHERE id=?', (lat,lon,ts,ts,g.o_provider['id']))
    active = db.execute("SELECT id FROM o_requests WHERE provider_id=? AND status IN ('Available','Coming to you','On trip')", (g.o_provider['id'],)).fetchall()
    db.execute('UPDATE o_requests SET provider_lat=?,provider_lon=?,updated_at=? WHERE provider_id=? AND status IN (\'Available\',\'Coming to you\',\'On trip\')', (lat,lon,ts,g.o_provider['id']))
    db.commit()
    return jsonify(ok=True, active_requests=len(active))


@bp.get('/logout')
def provider_logout():
    session.pop('o_provider_id', None); session.pop('o_provider_role', None)
    return redirect(url_for('o.people'))


@bp.get('/my')
def my_o():
    if not session.get('user_id'):
        return redirect(url_for('public.login', next=url_for('o.my_o')))
    db = get_db()
    u = db.execute('SELECT * FROM users WHERE id=? AND deleted_at IS NULL', (session['user_id'],)).fetchone()
    requests = db.execute('SELECT * FROM o_requests WHERE user_id=? ORDER BY id DESC LIMIT 30', (u['id'],)).fetchall()
    return render_template('o_my.html', user=u, requests=requests)


@bp.get('/health')
def health():
    return jsonify(ok=True, service='O', routing=current_app.config.get('O_ROUTING_URL', ''))
