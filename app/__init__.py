import os, secrets
from pathlib import Path
from flask import Flask, request
from .db import init_db

def _secret(path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        value = path.read_text().strip()
        if value: return value
    value = secrets.token_urlsafe(48); path.write_text(value)
    try: os.chmod(path, 0o600)
    except OSError: pass
    return value

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    import base64
    app.jinja_env.filters['b64encode'] = lambda b: base64.b64encode(b).decode('ascii')
    app.jinja_env.filters['fromjson'] = lambda s: __import__('json').loads(s or '[]')
    app.config.update(
        SECRET_KEY=os.environ.get('FLASK_SECRET_KEY') or _secret(Path(app.instance_path)/'session-secret.key'),
        DATABASE_PATH=os.environ.get('DATABASE_PATH', str(Path(app.instance_path)/'adventures.sqlite3')),
        UPLOAD_FOLDER=os.environ.get('UPLOAD_FOLDER', str(Path(app.instance_path)/'uploads')),
        BRAND_NAME=os.environ.get('BRAND_NAME','O'),
        O_ROUTING_URL=os.environ.get('O_ROUTING_URL','https://router.project-osrm.org'),
        ADMIN_PATH=os.environ.get('ADMIN_PATH','promise212324').strip('/'),
        ADMIN_USERNAME=os.environ.get('ADMIN_USERNAME',''),
        ADMIN_PASSWORD=os.environ.get('ADMIN_PASSWORD',''),
        MAX_CONTENT_LENGTH=12*1024*1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE','true').lower() in ('1','true','yes'),
    )
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)
    init_db(app)
    from .routes import bp
    from .admin import admin_bp
    from .o_platform import bp as o_bp
    from .o_admin import bp as o_admin_bp
    app.register_blueprint(bp)
    app.register_blueprint(admin_bp, url_prefix='/'+app.config['ADMIN_PATH'])
    app.register_blueprint(o_bp)
    app.register_blueprint(o_admin_bp)
    @app.errorhandler(404)
    def not_found(_): return __import__('flask').render_template('o_error.html', code=404, title='Page not found', message='That O route is not available.'), 404
    @app.errorhandler(403)
    def forbidden(_): return __import__('flask').render_template('o_error.html', code=403, title='Access denied', message='This O area is not available to this account.'), 403
    @app.errorhandler(500)
    def server_error(_): return __import__('flask').render_template('o_error.html', code=500, title='O is having trouble', message='Something went wrong on the server. The rest of the application is still protected.'), 500
    @app.after_request
    def headers(resp):
        resp.headers['X-Content-Type-Options']='nosniff'; resp.headers['X-Frame-Options']='DENY'; resp.headers['Referrer-Policy']='strict-origin-when-cross-origin'
        if request.path.startswith('/'+app.config['ADMIN_PATH']): resp.headers['Cache-Control']='no-store'
        return resp
    return app
app = create_app()
