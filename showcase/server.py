"""The live portfolio server (runs on PythonAnywhere).

Serves the built site and adds a password-protected /admin where the owner can
upload screenshots to any project, create new projects, edit text and hide things.
Everything the owner adds lives in DATA_DIR (outside the deployed site folder), so a
fresh `python -m showcase deploy` never wipes it."""
import hashlib, hmac, io, json, os, re, secrets, threading, time, uuid

from flask import Flask, abort, jsonify, redirect, request, send_from_directory, session

ROOT = os.environ.get('SHOWCASE_ROOT') or os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('SHOWCASE_DATA') or os.path.join(os.path.dirname(ROOT),
                                                           'portfolio_data')
UPLOADS = os.path.join(DATA_DIR, 'uploads')
CUSTOM = os.path.join(DATA_DIR, 'custom.json')
ADMIN = os.path.join(DATA_DIR, 'admin.json')
IMG_EXT = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
CATS = ['web', 'mobile', 'desktop', 'hw', 'ai', 'sim', 'tools', 'docs']
LOCK = threading.Lock()
os.makedirs(UPLOADS, exist_ok=True)


# ---------------------------------------------------------------- storage

def load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200_000).hex()
    return 'pbkdf2$%s$%s' % (salt, h)


def check_pw(pw, stored):
    try:
        _, salt, _ = stored.split('$')
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(hash_pw(pw, salt), stored)


def admin_cfg():
    cfg = load(ADMIN, {})
    if not cfg.get('secret'):
        cfg['secret'] = secrets.token_hex(32)
        save(ADMIN, cfg)
    return cfg


def base_projects():
    return load(os.path.join(ROOT, 'data.json'), [])


def custom():
    c = load(CUSTOM, {})
    c.setdefault('projects', {})
    return c


def merged(include_hidden=False):
    c = custom()['projects']
    out, seen = [], set()
    for i, p in enumerate(base_projects()):
        seen.add(p['slug'])
        out.append(apply(dict(p), c.get(p['slug'], {}), i))
    for slug, o in c.items():
        if slug not in seen and o.get('new'):
            out.append(apply({'slug': slug, 'title': slug, 'en': '', 'desc': '', 'bullets': [],
                              'cat': 'web', 'stack': [], 'repo': '', 'imgs': [],
                              'updated': '', 'featured': 10}, o, 1000))
    if not include_hidden:
        out = [p for p in out if not p.get('hidden') and not p.get('deleted') and p['imgs']]
    pos = {slug: i for i, slug in enumerate(custom().get('order', []))}   # admin drag & drop
    out.sort(key=lambda p: (pos.get(p['slug'], len(pos)), p.get('featured', 99), p['_order']))
    return out


def apply(p, o, order):
    for k in ('title', 'en', 'desc', 'cat', 'stack', 'repo', 'live_url', 'featured', 'hidden',
              'deleted'):
        if k in o and o[k] not in (None, ''):
            p[k] = o[k]
    hidden = set(o.get('hide_imgs', []))
    ups = [dict(u, kind='upload') for u in o.get('uploads', [])]
    rest = [i for i in p.get('imgs', []) if i['src'] not in hidden]
    p['imgs'] = ups + rest if o.get('uploads_first', True) else rest + ups
    if o.get('img_order'):                      # admin drag & drop of pictures
        at = {src: i for i, src in enumerate(o['img_order'])}
        p['imgs'].sort(key=lambda i: at.get(i['src'], len(at)))
    if p['imgs']:
        p['kind'] = p['imgs'][0]['kind']
        p['thumb'] = p['imgs'][0].get('thumb') or p['imgs'][0]['src'] \
            if p['imgs'][0]['kind'] == 'upload' else p.get('thumb') or p['imgs'][0]['src']
    p['_order'] = order
    return p


# ---------------------------------------------------------------- images

def store_image(slug, fs):
    ext = (fs.filename or '').rsplit('.', 1)[-1].lower()
    if ext not in IMG_EXT:
        raise ValueError('نوع الملف غير مدعوم: %s' % fs.filename)
    blob = fs.read()
    if len(blob) > 20_000_000:
        raise ValueError('الصورة أكبر من 20MB: %s' % fs.filename)
    d = os.path.join(UPLOADS, slug)
    os.makedirs(d, exist_ok=True)
    name = uuid.uuid4().hex[:12]
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(blob))
        im.load()
        im = im.convert('RGB')
        w, h = im.size
        big = im.copy()
        if w > 1600:
            big = big.resize((1600, round(h * 1600 / w)), Image.LANCZOS)
        big.save(os.path.join(d, name + '.webp'), 'WEBP', quality=82)
        th = im.copy()
        if w > 720:
            th = th.resize((720, round(h * 720 / w)), Image.LANCZOS)
        th.save(os.path.join(d, name + '_t.webp'), 'WEBP', quality=78)
        src, thumb = 'u/%s/%s.webp' % (slug, name), 'u/%s/%s_t.webp' % (slug, name)
        w, h = big.size
    except ImportError:
        if not blob[:12].startswith((b'\x89PNG', b'\xff\xd8', b'GIF8', b'RIFF')):
            raise ValueError('الملف ليس صورة: %s' % fs.filename)
        open(os.path.join(d, name + '.' + ext), 'wb').write(blob)
        src = thumb = 'u/%s/%s.%s' % (slug, name, ext)
        w, h = 1600, 1000
    except Exception:
        raise ValueError('الملف ليس صورة صالحة: %s' % fs.filename)
    return {'src': src, 'thumb': thumb, 'w': w, 'h': h,
            'device': 'mobile' if h > w * 1.3 else 'desktop'}


def slugify(s):
    s = re.sub(r'[^a-z0-9]+', '-', (s or '').lower()).strip('-')
    return s[:50] or 'p-' + uuid.uuid4().hex[:6]


# ---------------------------------------------------------------- app

app = Flask(__name__)
app.secret_key = admin_cfg()['secret']
app.config.update(MAX_CONTENT_LENGTH=120_000_000, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=30 * 86400)


def profile():
    me = load(os.path.join(ROOT, 'profile.json'), {})
    me.update(custom().get('profile', {}))
    return me


def page_with_data(fn):
    with open(os.path.join(ROOT, fn), encoding='utf-8') as f:
        html = f.read()
    data = json.dumps(merged(), ensure_ascii=False).replace('</', '<\\/')
    me = json.dumps(profile(), ensure_ascii=False).replace('</', '<\\/')
    html = re.sub(r'/\*DATA\*/.*?/\*END\*/', lambda m: '/*DATA*/%s/*END*/' % data, html,
                  count=1, flags=re.S)
    return re.sub(r'/\*ME\*/.*?/\*MEEND\*/', lambda m: '/*ME*/%s/*MEEND*/' % me, html,
                  count=1, flags=re.S)


@app.route('/')
def index():
    return page_with_data('index.html'), 200, {'Cache-Control': 'no-cache'}


@app.route('/u/<path:p>')
def uploads(p):
    return send_from_directory(UPLOADS, p, max_age=604800)


@app.route('/<path:p>')
def static_files(p):
    if p.startswith(('data.json', 'profile.json', 'server.py')) or p.endswith('.py'):
        abort(404)
    full = os.path.join(ROOT, p)
    if os.path.isfile(full):
        return send_from_directory(ROOT, p, max_age=604800)
    return index()


def authed():
    return session.get('admin') is True


def need_auth():
    if not authed():
        abort(401)
    tok = request.headers.get('X-CSRF') or request.form.get('csrf')
    if request.method == 'POST' and tok != session.get('csrf'):
        abort(403)


@app.route('/admin', methods=['GET'])
def admin_page():
    if not authed():
        return LOGIN_HTML.replace('{{ERR}}', request.args.get('e', '') and
                                  '<p class="err">كلمة السر غلط</p>')
    return ADMIN_HTML.replace('{{CSRF}}', session['csrf'])


@app.route('/admin/login', methods=['POST'])
def login():
    cfg = admin_cfg()
    if cfg.get('password') and check_pw(request.form.get('password', ''), cfg['password']):
        session.permanent = True
        session['admin'] = True
        session['csrf'] = secrets.token_hex(16)
        return redirect('/admin')
    time.sleep(1.5)
    return redirect('/admin?e=1')


@app.route('/admin/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect('/')


@app.route('/admin/api/projects')
def api_projects():
    need_auth()
    c = custom()['projects']
    ps = merged(include_hidden=True)
    for p in ps:
        o = c.get(p['slug'], {})
        p['is_new'] = bool(o.get('new'))
        p['hidden_imgs'] = o.get('hide_imgs', [])
        p['deleted'] = bool(o.get('deleted'))
    base = {p['slug']: p for p in base_projects()}
    for p in ps:     # show hidden built-in images too, so they can be restored
        if p['slug'] in base:
            p['all_imgs'] = [dict(u, kind='upload') for u in c.get(p['slug'], {}).get(
                'uploads', [])] + base[p['slug']]['imgs']
        else:
            p['all_imgs'] = p['imgs']
        at = {src: i for i, src in enumerate(c.get(p['slug'], {}).get('img_order', []))}
        p['all_imgs'].sort(key=lambda i: at.get(i['src'], len(at)))
    return jsonify(ps)


@app.route('/admin/api/save', methods=['POST'])
def api_save():
    """Create or edit a project and attach any uploaded images."""
    need_auth()
    f = request.form
    slug = f.get('slug', '').strip()
    with LOCK:
        c = custom()
        known = {p['slug'] for p in base_projects()} | set(c['projects'])
        if not slug or slug == '__new__':
            title = f.get('title', '').strip()
            if not title:
                return jsonify(error='اكتب اسم المشروع'), 400
            slug = slugify(f.get('en') or title)
            while slug in known:
                slug += '-2'
            c['projects'][slug] = {'new': True, 'created': time.strftime('%Y-%m-%d')}
        elif slug not in known:
            return jsonify(error='مشروع غير موجود'), 404
        o = c['projects'].setdefault(slug, {})
        for k in ('title', 'en', 'desc', 'repo', 'live_url'):
            if k in f:
                o[k] = f.get(k, '').strip()
        if f.get('cat') in CATS:
            o['cat'] = f['cat']
        if 'stack' in f:
            o['stack'] = [s.strip() for s in re.split(r'[,،]', f['stack']) if s.strip()][:8]
        if f.get('featured', '').strip().isdigit():
            o['featured'] = int(f['featured'])
        if 'hidden' in f:
            o['hidden'] = f['hidden'] == '1'
        errors = []
        for fs in request.files.getlist('images'):
            if not fs or not fs.filename:
                continue
            try:
                o.setdefault('uploads', []).append(store_image(slug, fs))
            except ValueError as e:
                errors.append(str(e))
        if o.get('new') and not o.get('uploads'):
            errors.append('المشروع الجديد يحتاج صورة وحدة على الأقل حتى يظهر بالموقع')
        save(CUSTOM, c)
    return jsonify(ok=True, slug=slug, errors=errors)


@app.route('/admin/api/image', methods=['POST'])
def api_image():
    """Delete an uploaded image, hide/restore a built-in one, or move it to the front."""
    need_auth()
    slug, src, action = request.form.get('slug'), request.form.get('src'), \
        request.form.get('action')
    with LOCK:
        c = custom()
        o = c['projects'].setdefault(slug, {})
        ups = o.setdefault('uploads', [])
        up = next((u for u in ups if u['src'] == src), None)
        if action == 'delete' and up:
            ups.remove(up)
            for k in ('src', 'thumb'):
                p = os.path.normpath(os.path.join(UPLOADS, up[k][2:]))
                if p.startswith(UPLOADS) and os.path.isfile(p):
                    os.remove(p)
        elif action == 'hide':
            o.setdefault('hide_imgs', [])
            if src not in o['hide_imgs']:
                o['hide_imgs'].append(src)
        elif action == 'show':
            o['hide_imgs'] = [s for s in o.get('hide_imgs', []) if s != src]
        elif action == 'first' and up:
            ups.remove(up)
            ups.insert(0, up)
        else:
            return jsonify(error='bad action'), 400
        save(CUSTOM, c)
    return jsonify(ok=True)


@app.route('/admin/api/delete', methods=['POST'])
def api_delete():
    """Projects made here are deleted for good; built-in ones go to the trash (restorable,
    and a redeploy does not bring them back)."""
    need_auth()
    slug = request.form.get('slug')
    with LOCK:
        c = custom()
        o = c['projects'].get(slug)
        if o and o.get('new'):
            import shutil
            shutil.rmtree(os.path.join(UPLOADS, slugify(slug)), ignore_errors=True)
            del c['projects'][slug]
            c['order'] = [x for x in c.get('order', []) if x != slug]
            save(CUSTOM, c)
            return jsonify(ok=True, gone=True)
        if slug not in {p['slug'] for p in base_projects()}:
            return jsonify(error='مشروع غير موجود'), 404
        c['projects'].setdefault(slug, {})['deleted'] = True
        save(CUSTOM, c)
    return jsonify(ok=True, trashed=True)


@app.route('/admin/api/restore', methods=['POST'])
def api_restore():
    need_auth()
    slug = request.form.get('slug')
    with LOCK:
        c = custom()
        if slug in c['projects']:
            c['projects'][slug].pop('deleted', None)
            save(CUSTOM, c)
    return jsonify(ok=True)


@app.route('/admin/api/order', methods=['POST'])
def api_order():
    """Order of projects on the site: the full list of slugs, top first."""
    need_auth()
    slugs = (request.get_json(silent=True) or {}).get('slugs')
    if not isinstance(slugs, list) or not all(isinstance(x, str) for x in slugs):
        return jsonify(error='bad order'), 400
    with LOCK:
        c = custom()
        known = {p['slug'] for p in base_projects()} | set(c['projects'])
        c['order'] = [x for x in dict.fromkeys(slugs) if x in known]
        save(CUSTOM, c)
    return jsonify(ok=True)


@app.route('/admin/api/img_order', methods=['POST'])
def api_img_order():
    """Order of one project's pictures: the first one is the card picture."""
    need_auth()
    j = request.get_json(silent=True) or {}
    slug, srcs = j.get('slug'), j.get('srcs')
    if not isinstance(srcs, list) or not all(isinstance(x, str) for x in srcs):
        return jsonify(error='bad order'), 400
    with LOCK:
        c = custom()
        known = {p['slug'] for p in base_projects()} | set(c['projects'])
        if slug not in known:
            return jsonify(error='مشروع غير موجود'), 404
        c['projects'].setdefault(slug, {})['img_order'] = list(dict.fromkeys(srcs))[:200]
        save(CUSTOM, c)
    return jsonify(ok=True)


@app.route('/admin/api/profile', methods=['GET', 'POST'])
def api_profile():
    """Read or edit the 'about me' block (name, photo, bio, experience...)."""
    need_auth()
    if request.method == 'GET':
        return jsonify(profile())
    f = request.form
    lines = lambda k: [l.strip() for l in f.get(k, '').splitlines() if l.strip()]
    with LOCK:
        c = custom()
        o = c.setdefault('profile', {})
        for k in ('name', 'name_en', 'role', 'bio', 'location', 'email', 'education', 'languages'):
            if k in f:
                o[k] = f[k].strip()
        if 'skills' in f:
            o['skills'] = [x.strip() for x in re.split(r'[,،\n]', f['skills']) if x.strip()]
        if 'training' in f:
            o['training'] = lines('training')
        if 'experience' in f:
            o['experience'] = []
            for l in lines('experience'):
                parts = [x.strip() for x in l.split('|')] + ['', '']
                o['experience'].append({'title': parts[0], 'years': parts[1], 'text': parts[2]})
        if 'highlights' in f:
            o['highlights'] = []
            for l in lines('highlights'):
                parts = [x.strip() for x in l.split('|')] + ['', '']
                o['highlights'].append({'icon': parts[0], 'title': parts[1], 'text': parts[2]})
        if 'stats' in f:
            o['stats'] = [[x.strip() for x in (l.split('|') + [''])[:2]] for l in lines('stats')]
        ph = request.files.get('photo')
        if ph and ph.filename:
            try:
                o['photo'] = store_image('me', ph)['src']
            except ValueError as e:
                return jsonify(error=str(e)), 400
        save(CUSTOM, c)
    return jsonify(ok=True)


@app.route('/admin/api/password', methods=['POST'])
def api_password():
    need_auth()
    old, new = request.form.get('old', ''), request.form.get('new', '')
    cfg = admin_cfg()
    if not check_pw(old, cfg.get('password', '')):
        return jsonify(error='كلمة السر الحالية غلط'), 400
    if len(new) < 8:
        return jsonify(error='كلمة السر لازم 8 أحرف أو أكثر'), 400
    cfg['password'] = hash_pw(new)
    save(ADMIN, cfg)
    return jsonify(ok=True)


# ---------------------------------------------------------------- optional automation API
# Import inside the package for local testing, or from the deployed site directory.
try:
    from .project_api import register as register_project_api
except ImportError:
    from project_api import register as register_project_api

register_project_api(app, lock=LOCK, data_file=CUSTOM, base_projects=base_projects,
                     custom=custom, merged=merged, save=save, store_image=store_image,
                     categories=CATS)


# ---------------------------------------------------------------- pages

STYLE = '''<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>
:root{--cream:#FFF6EA;--paper:#fff;--ink:#16130D;--dim:#5C554A;--gold:#FFC93C;--coral:#FF5C39;--teal:#12B99C;
 --line:3px solid var(--ink);--pop:-5px 5px 0 var(--ink)}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--cream);color:var(--ink);font-family:Cairo,Tahoma,sans-serif;line-height:1.7}
.wrap{max-width:980px;margin:0 auto;padding:0 16px 60px}
header{display:flex;align-items:center;gap:12px;padding:16px 0;border-bottom:var(--line);margin-bottom:24px}
header h1{font-size:20px;font-weight:900;flex:1}header img{width:36px}
.card{background:var(--paper);border:var(--line);border-radius:20px;box-shadow:var(--pop);padding:20px;margin-bottom:24px}
h2{font-size:19px;font-weight:900;margin-bottom:12px}
label{display:block;font-weight:700;font-size:14px;margin:10px 0 4px}
input,select,textarea{width:100%;font:600 15px Cairo,sans-serif;border:2.5px solid var(--ink);border-radius:12px;
 padding:8px 12px;background:#fff;color:#16130D}
textarea{min-height:90px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:640px){.row{grid-template-columns:1fr}}
.btn{display:inline-flex;align-items:center;gap:6px;font:700 15px Cairo,sans-serif;border:var(--line);border-radius:12px;
 padding:8px 18px;background:var(--gold);color:#16130D;box-shadow:-3px 3px 0 var(--ink);cursor:pointer}
.btn.white{background:#fff}.btn.red{background:var(--coral);color:#fff}.btn.sm{font-size:12px;padding:3px 10px;box-shadow:none;border-width:2px}
.drop{border:3px dashed var(--ink);border-radius:16px;padding:26px;text-align:center;background:#FFFBF3;cursor:pointer;margin-top:12px}
.drop.over{background:#FFF0C2}
.previews,.imgs{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin-top:12px}
.previews img{width:100%;height:100px;object-fit:cover;border-radius:10px;border:2px solid var(--ink)}
.im{border:2px solid var(--ink);border-radius:12px;overflow:hidden;background:#fff}
.im img{width:100%;height:100px;object-fit:cover;object-position:top;display:block}
.im.off img{opacity:.3}.im div{display:flex;flex-wrap:wrap;gap:4px;padding:6px;align-items:center}
.im small{font-size:11px;font-weight:700;flex:1 0 100%}
.msg{margin-top:12px;font-weight:700}.msg.ok{color:#0B8A73}.msg.bad{color:#C2361C}
.err{color:#C2361C;font-weight:700;margin-top:10px}
.hide{display:none}
.chk{display:flex;gap:8px;align-items:center;margin-top:12px;font-weight:700}.chk input{width:auto}
</style>'''

LOGIN_HTML = '''<!doctype html><html lang="ar" dir="rtl"><head>%s<title>دخول الإدارة</title></head><body>
<div class="wrap" style="max-width:420px;padding-top:12vh"><div class="card">
<h2>إدارة المعرض</h2><form method="post" action="/admin/login">
<label>كلمة السر</label><input type="password" name="password" autofocus required>
<p style="margin-top:14px"><button class="btn">دخول</button></p>{{ERR}}</form></div>
<p style="text-align:center"><a href="/">← رجوع للموقع</a></p></div></body></html>''' % STYLE

ADMIN_HTML = '''<!doctype html><html lang="ar" dir="rtl"><head>%s<title>إدارة المعرض</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Sortable/1.15.2/Sortable.min.js"></script>
<style>
.wrap{max-width:1280px}
.tabs{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.tab{font:800 15px Cairo,sans-serif;border:var(--line);border-radius:12px;padding:6px 18px;background:#fff;cursor:pointer}
.tab.on{background:var(--ink);color:#fff}
.grid2{display:grid;grid-template-columns:380px 1fr;gap:24px;align-items:start}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
.side{position:sticky;top:12px;max-height:calc(100vh - 24px);display:flex;flex-direction:column;padding:16px}
@media(max-width:900px){.side{position:static;max-height:none}}
.tools{display:flex;gap:8px;margin-bottom:10px}.tools input{flex:1}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.chip{font:700 12px Cairo,sans-serif;border:2px solid var(--ink);border-radius:20px;padding:1px 10px;background:#fff;cursor:pointer}
.chip.on{background:var(--gold)}
.list{overflow:auto;flex:1;display:flex;flex-direction:column;gap:6px;padding:2px}
.it{display:flex;align-items:center;gap:8px;border:2px solid var(--ink);border-radius:12px;background:#fff;padding:5px 6px;cursor:pointer}
.it.sel{background:#FFF0C2;box-shadow:-3px 3px 0 var(--ink)}
.it.off{opacity:.55}.it.off .tt::after{content:' · مخفي';color:var(--coral);font-size:11px}
.it img{width:54px;height:38px;object-fit:cover;object-position:top;border-radius:7px;border:1.5px solid var(--ink);flex:none}
.it .tt{flex:1;min-width:0;font-weight:700;font-size:13px;line-height:1.3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.it .tt small{display:block;color:var(--dim);font-weight:600;font-size:11px}
.num{font:800 11px Cairo;color:var(--dim);width:20px;text-align:center;flex:none}
.handle{cursor:grab;font-size:18px;padding:0 4px;color:var(--dim);touch-action:none;flex:none}
.ib{border:2px solid var(--ink);background:#fff;border-radius:8px;width:30px;height:30px;cursor:pointer;font-size:15px;flex:none;display:grid;place-items:center}
.ib:hover{background:var(--gold)}.ib.red:hover{background:var(--coral);color:#fff}
.ghost{opacity:.35}.chosen{box-shadow:-4px 4px 0 var(--teal)!important}
.trash{margin-top:10px;border-top:2px dashed var(--ink);padding-top:8px;font-size:13px}
.trash summary{cursor:pointer;font-weight:800}
.imgs{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}
.im{position:relative}.im img{height:110px;cursor:grab}
.im .badge{position:absolute;top:6px;right:6px;background:var(--gold);border:2px solid var(--ink);border-radius:8px;font:800 11px Cairo;padding:0 6px}
.toast{position:fixed;bottom:20px;left:50%%;transform:translateX(-50%%);background:var(--ink);color:#fff;font-weight:700;
 padding:8px 20px;border-radius:12px;opacity:0;transition:.25s;pointer-events:none;z-index:9}
.toast.show{opacity:1}
.empty{color:var(--dim);text-align:center;padding:40px 10px;font-weight:700}
.hint{color:var(--dim);font-size:13px;font-weight:600}
</style></head><body>
<div class="wrap">
<header><img src="/favicon.svg" alt=""><h1>إدارة المعرض</h1><a class="btn white" href="/" target="_blank">عرض الموقع ↗</a>
<form method="post" action="/admin/logout"><button class="btn white">خروج</button></form></header>
<div class="tabs"><button class="tab on" data-t="projects">📂 المشاريع</button><button class="tab" data-t="me">👤 عني</button>
 <button class="tab" data-t="pw">🔑 كلمة السر</button></div>

<section id="t-projects"><div class="grid2">
 <div class="card side">
  <div class="tools"><input id="q" placeholder="ابحث عن مشروع…"><button class="btn" id="newBtn" title="مشروع جديد">➕ جديد</button></div>
  <div class="chips" id="cats"></div>
  <p class="hint" style="margin-bottom:6px">اسحب ☰ حتى ترتب المشاريع — الترتيب ينحفظ وينطبق بالموقع فوراً.</p>
  <div class="list" id="list"></div>
  <details class="trash" id="trashBox"><summary>🗑 سلة المحذوفات (<span id="trashN">0</span>)</summary><div class="list" id="trash" style="margin-top:8px"></div></details>
 </div>

 <div class="card" id="editor">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap">
   <h2 id="edTitle" style="flex:1;margin:0">مشروع جديد</h2>
   <button class="btn sm white" id="topBtn">⬆ أول القائمة</button>
   <button class="btn sm white" id="eyeBtn">👁 إخفاء</button>
   <button class="btn sm red" id="delBtn">🗑 حذف</button></div>
  <div class="row"><div><label>الاسم (عربي)</label><input id="title"></div>
   <div><label>الاسم (إنكليزي)</label><input id="en" dir="ltr"></div></div>
  <label>الوصف</label><textarea id="desc" dir="auto"></textarea>
  <div class="row"><div><label>التصنيف</label><select id="cat"></select></div>
   <div><label>التقنيات (افصل بفاصلة)</label><input id="stack" dir="ltr" placeholder="Flutter, Django"></div></div>
  <div class="row"><div><label>رابط GitHub</label><input id="repo" dir="ltr"></div>
   <div><label>رابط تجربة مباشرة</label><input id="live_url" dir="ltr"></div></div>

  <h2 style="margin-top:22px">الصور <span class="hint">— اسحب الصورة حتى ترتبها؛ الأولى هي صورة الكارت</span></h2>
  <div class="imgs" id="imgs"></div>
  <div class="drop" id="drop">اسحب صور جديدة هنا، الصقها (Ctrl+V)، أو <b>اضغط للاختيار</b>
   <input type="file" id="files" accept="image/*" multiple class="hide"></div>
  <div class="previews" id="previews"></div>
  <p style="margin-top:16px;display:flex;gap:10px;flex-wrap:wrap"><button class="btn" id="saveBtn">💾 حفظ</button></p>
  <div class="msg" id="msg"></div>
 </div>
</div></section>

<section id="t-me" class="hide"><div class="card"><h2>عني — صورتي ومعلوماتي</h2>
 <div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
  <img id="me_ph" src="" alt="" style="width:96px;height:96px;border-radius:22px;border:3px solid #16130D;object-fit:cover">
  <label class="btn white" style="margin:0">تغيير الصورة<input type="file" id="me_photo" accept="image/*" class="hide"></label></div>
 <div class="row"><div><label>الاسم</label><input id="me_name"></div><div><label>الاسم بالإنكليزي</label><input id="me_name_en" dir="ltr"></div></div>
 <div class="row"><div><label>التخصص</label><input id="me_role"></div><div><label>المكان</label><input id="me_location"></div></div>
 <label>نبذة عني</label><textarea id="me_bio"></textarea>
 <div class="row"><div><label>الإيميل</label><input id="me_email" dir="ltr"></div><div><label>اللغات</label><input id="me_languages"></div></div>
 <label>الدراسة</label><input id="me_education">
 <label>الخبرة — كل سطر: العنوان | السنوات | الوصف</label><textarea id="me_experience" style="min-height:130px"></textarea>
 <label>شنو أقدّم — كل سطر: أيقونة | العنوان | الوصف</label><textarea id="me_highlights" style="min-height:130px"></textarea>
 <label>دورات وتدريب وبحوث — كل سطر وحدة</label><textarea id="me_training"></textarea>
 <label>المهارات — افصل بفاصلة</label><textarea id="me_skills" dir="ltr"></textarea>
 <label>أرقام إضافية — كل سطر: الرقم | الوصف</label><textarea id="me_stats"></textarea>
 <p style="margin-top:14px"><button class="btn" id="meBtn">حفظ معلوماتي</button></p><div class="msg" id="memsg"></div></div></section>

<section id="t-pw" class="hide"><div class="card" style="max-width:560px"><h2>تغيير كلمة السر</h2>
 <label>الحالية</label><input type="password" id="pw_old">
 <label>الجديدة (8 أحرف أو أكثر)</label><input type="password" id="pw_new">
 <p style="margin-top:14px"><button class="btn white" id="pwBtn">تغيير</button></p><div class="msg" id="pwmsg"></div></div></section>
</div>
<div class="toast" id="toast"></div>
<script>
const CSRF='{{CSRF}}';
const KL={live:'لقطة حقيقية',upload:'صورة مرفوعة',template:'من القوالب',repo:'صور المشروع',demo:'نسخة تجريبية',mockup:'تصور من الكود',cover:'غلاف'};
const CATS={web:'ويب',mobile:'موبايل',desktop:'ديسكتوب',hw:'أجهزة و IoT',ai:'ذكاء اصطناعي',sim:'شبكات ومحاكاة',tools:'أدوات',docs:'أبحاث وملاحظات'};
const F=['title','en','desc','cat','stack','repo','live_url'];
const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let P=[], cur=null, chosen=[], cat='', dirty=false;
$('#cat').innerHTML=Object.entries(CATS).map(([k,v])=>`<option value="${k}">${v}</option>`).join('');
async function post(url,fd){fd.append('csrf',CSRF);const r=await fetch(url,{method:'POST',body:fd,headers:{'X-CSRF':CSRF}});return res(r)}
async function postJ(url,o){const r=await fetch(url,{method:'POST',body:JSON.stringify(o),headers:{'X-CSRF':CSRF,'Content-Type':'application/json'}});return res(r)}
async function res(r){let j={};try{j=await r.json()}catch(e){j={error:'خطأ '+r.status}};if(!r.ok&&!j.error)j.error='خطأ '+r.status;return j}
function msg(el,t,ok){el.textContent=t;el.className='msg '+(ok?'ok':'bad')}
let tt;function toast(t){const e=$('#toast');e.textContent=t;e.classList.add('show');clearTimeout(tt);tt=setTimeout(()=>e.classList.remove('show'),1800)}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===b));
 ['projects','me','pw'].forEach(t=>$('#t-'+t).classList.toggle('hide',t!==b.dataset.t))});

async function load(keep){P=await (await fetch('/admin/api/projects')).json();
 const live=P.filter(p=>!p.deleted);drawCats(live);drawList();drawTrash();
 select(keep&&P.find(p=>p.slug===keep)?keep:(cur&&P.find(p=>p.slug===cur.slug)?cur.slug:(live[0]||{}).slug))}
function drawCats(live){const n={};live.forEach(p=>n[p.cat]=(n[p.cat]||0)+1);
 $('#cats').innerHTML=`<button class="chip ${cat?'':'on'}" data-c="">الكل ${live.length}</button>`+
  Object.entries(CATS).filter(([k])=>n[k]).map(([k,v])=>`<button class="chip ${cat===k?'on':''}" data-c="${k}">${v} ${n[k]}</button>`).join('')}
$('#cats').onclick=e=>{const b=e.target.closest('.chip');if(!b)return;cat=b.dataset.c;drawCats(P.filter(p=>!p.deleted));drawList()};
$('#q').oninput=drawList;
function thumb(p){const i=(p.all_imgs||p.imgs||[]).find(i=>!(p.hidden_imgs||[]).includes(i.src));return i?'/'+(i.thumb||i.src):'/favicon.svg'}
function row(p,i,trash){return `<div class="it ${p.hidden?'off':''} ${cur&&cur.slug===p.slug?'sel':''}" data-s="${esc(p.slug)}">
 ${trash?'':`<span class="handle" title="اسحب للترتيب">☰</span><span class="num">${i+1}</span>`}
 <img src="${thumb(p)}" loading="lazy" alt=""><span class="tt">${esc(p.title)}<small>${CATS[p.cat]||''}${p.is_new?' · مضاف من هنا':''}</small></span>
 ${trash?`<button class="ib" data-a="restore" title="استرجاع">↩</button>`:
 `<button class="ib" data-a="eye" title="${p.hidden?'إظهار':'إخفاء'}">${p.hidden?'🙈':'👁'}</button><button class="ib red" data-a="del" title="حذف">🗑</button>`}</div>`}
function drawList(){const q=$('#q').value.trim().toLowerCase();const live=P.filter(p=>!p.deleted);
 const show=live.filter(p=>(!cat||p.cat===cat)&&(!q||(p.title+' '+p.en+' '+p.slug).toLowerCase().includes(q)));
 $('#list').innerHTML=show.length?show.map(p=>row(p,live.indexOf(p),false)).join(''):'<p class="empty">ماكو نتائج</p>';
 sortList.option('disabled',!!(q||cat))}
function drawTrash(){const t=P.filter(p=>p.deleted);$('#trashN').textContent=t.length;
 $('#trash').innerHTML=t.map(p=>row(p,0,true)).join('')||'<p class="hint">فارغة</p>'}
const sortList=Sortable.create($('#list'),{handle:'.handle',animation:160,ghostClass:'ghost',chosenClass:'chosen',
 onEnd:async()=>{const order=[...$('#list').children].map(e=>e.dataset.s).filter(Boolean);
  const rest=P.filter(p=>!order.includes(p.slug)).map(p=>p.slug);
  P.sort((a,b)=>[...order,...rest].indexOf(a.slug)-[...order,...rest].indexOf(b.slug));drawList();
  const j=await postJ('/admin/api/order',{slugs:[...order,...rest]});toast(j.error||'انحفظ الترتيب ✓')}});
async function saveOrder(){const j=await postJ('/admin/api/order',{slugs:P.map(p=>p.slug)});toast(j.error||'انحفظ الترتيب ✓')}
$('#list').onclick=async e=>{const it=e.target.closest('.it');if(!it)return;const b=e.target.closest('.ib');const p=P.find(x=>x.slug===it.dataset.s);
 if(!b){if(dirty&&!confirm('عندك تعديلات ما انحفظت، تكمل؟'))return;return select(p.slug)}
 if(b.dataset.a==='eye')return setHidden(p,!p.hidden);
 if(b.dataset.a==='del')return del(p)};
$('#trash').onclick=async e=>{const b=e.target.closest('.ib');if(!b)return;const fd=new FormData();fd.append('slug',b.closest('.it').dataset.s);
 const j=await post('/admin/api/restore',fd);toast(j.error||'رجع المشروع ✓');load()};
async function setHidden(p,h){const fd=new FormData();fd.append('slug',p.slug);fd.append('hidden',h?'1':'0');
 const j=await post('/admin/api/save',fd);toast(j.error||(h?'انخفى من الموقع':'صار ظاهر بالموقع'));load(cur&&cur.slug)}
async function del(p){if(!confirm(p.is_new?`تحذف «${p.title}» وكل صوره نهائياً؟`:`تنقل «${p.title}» لسلة المحذوفات؟ (تقدر ترجعه)`))return;
 const fd=new FormData();fd.append('slug',p.slug);const j=await post('/admin/api/delete',fd);toast(j.error||'انحذف ✓');
 if(cur&&cur.slug===p.slug)cur=null;load()}

function select(slug){cur=P.find(p=>p.slug===slug)||null;dirty=false;chosen=[];$('#previews').innerHTML='';$('#msg').textContent='';
 document.querySelectorAll('#list .it').forEach(e=>e.classList.toggle('sel',cur&&e.dataset.s===cur.slug));
 $('#edTitle').textContent=cur?cur.title:'➕ مشروع جديد';
 F.forEach(k=>$('#'+k).value=cur?(Array.isArray(cur[k])?cur[k].join(', '):(cur[k]??'')):(k==='cat'?'web':''));
 ['topBtn','eyeBtn','delBtn'].forEach(b=>$('#'+b).classList.toggle('hide',!cur));
 if(cur)$('#eyeBtn').textContent=cur.hidden?'🙈 إظهار':'👁 إخفاء';
 drawImgs()}
function drawImgs(){if(!cur){$('#imgs').innerHTML='<p class="hint">ارفع صورة وحدة على الأقل حتى يظهر المشروع بالموقع.</p>';return}
 const hid=new Set(cur.hidden_imgs);let first=true;
 $('#imgs').innerHTML=cur.all_imgs.map(im=>{const off=hid.has(im.src);const up=im.kind==='upload';const b=!off&&first;if(b)first=false;
  return `<div class="im ${off?'off':''}" data-s="${esc(im.src)}">${b?'<span class="badge">صورة الكارت</span>':''}<img src="/${im.thumb||im.src}" loading="lazy" alt="">
  <div><small>${KL[im.kind]||im.kind}${off?' · مخفية':''}</small>
  <button class="btn sm white" data-a="first">⬆ أولى</button>
  ${up?`<button class="btn sm red" data-a="delete">حذف</button>`:`<button class="btn sm ${off?'':'white'}" data-a="${off?'show':'hide'}">${off?'إظهار':'إخفاء'}</button>`}</div></div>`}).join('')}
const sortImgs=Sortable.create($('#imgs'),{animation:160,ghostClass:'ghost',chosenClass:'chosen',filter:'button',preventOnFilter:false,
 onEnd:()=>saveImgOrder([...$('#imgs').children].map(e=>e.dataset.s))});
async function saveImgOrder(srcs){if(!cur)return;cur.all_imgs.sort((a,b)=>srcs.indexOf(a.src)-srcs.indexOf(b.src));drawImgs();
 const j=await postJ('/admin/api/img_order',{slug:cur.slug,srcs});toast(j.error||'انحفظ ترتيب الصور ✓');load(cur.slug)}
$('#imgs').onclick=async e=>{const b=e.target.closest('button');if(!b||!cur)return;const src=b.closest('.im').dataset.s;
 if(b.dataset.a==='first'){const s=cur.all_imgs.map(i=>i.src).filter(x=>x!==src);return saveImgOrder([src,...s])}
 if(b.dataset.a==='delete'&&!confirm('تحذف الصورة نهائياً؟'))return;
 const fd=new FormData();fd.append('slug',cur.slug);fd.append('src',src);fd.append('action',b.dataset.a);
 const j=await post('/admin/api/image',fd);toast(j.error||'تم ✓');load(cur.slug)};
$('#topBtn').onclick=()=>{const i=P.indexOf(cur);P.splice(i,1);P.unshift(cur);drawList();saveOrder()};
$('#eyeBtn').onclick=()=>setHidden(cur,!cur.hidden);
$('#delBtn').onclick=()=>del(cur);
$('#newBtn').onclick=()=>{if(dirty&&!confirm('عندك تعديلات ما انحفظت، تكمل؟'))return;select(null);$('#title').focus()};
F.forEach(k=>$('#'+k).addEventListener('input',()=>dirty=true));
const drop=$('#drop');drop.onclick=()=>$('#files').click();
drop.ondragover=e=>{e.preventDefault();drop.classList.add('over')};drop.ondragleave=()=>drop.classList.remove('over');
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('over');add(e.dataTransfer.files)};
$('#files').onchange=e=>add(e.target.files);
document.addEventListener('paste',e=>{if($('#t-projects').classList.contains('hide'))return;const f=[...e.clipboardData.files];if(f.length)add(f)});
function add(fs){chosen.push(...[...fs].filter(f=>f.type.startsWith('image/')));dirty=true;
 $('#previews').innerHTML=chosen.map((f,i)=>`<div class="im"><img src="${URL.createObjectURL(f)}" alt=""><div><button class="btn sm red" data-i="${i}">شيل</button></div></div>`).join('')}
$('#previews').onclick=e=>{const b=e.target.closest('button');if(!b)return;chosen.splice(+b.dataset.i,1);add([])};
$('#saveBtn').onclick=async()=>{const b=$('#saveBtn');b.disabled=true;msg($('#msg'),'جاري الحفظ…',true);
 const fd=new FormData();fd.append('slug',cur?cur.slug:'__new__');F.forEach(k=>fd.append(k,$('#'+k).value));
 chosen.forEach(f=>fd.append('images',f,f.name));
 const j=await post('/admin/api/save',fd);b.disabled=false;if(j.error)return msg($('#msg'),j.error);
 chosen=[];$('#previews').innerHTML='';$('#files').value='';dirty=false;
 msg($('#msg'),j.errors&&j.errors.length?'انحفظ، بس: '+j.errors.join(' · '):'انحفظ ✓ — التغيير ظاهر بالموقع هسه',!(j.errors&&j.errors.length));
 load(j.slug)};
window.onbeforeunload=()=>dirty?'':undefined;
$('#pwBtn').onclick=async()=>{const fd=new FormData();fd.append('old',$('#pw_old').value);fd.append('new',$('#pw_new').value);
 const j=await post('/admin/api/password',fd);msg($('#pwmsg'),j.error||'تغيّرت كلمة السر ✓',!j.error)};
const MEF=['name','name_en','role','location','bio','email','languages','education'];
async function loadMe(){const m=await (await fetch('/admin/api/profile')).json();
 MEF.forEach(k=>$('#me_'+k).value=m[k]||'');$('#me_ph').src='/'+(m.photo||'favicon.svg');
 $('#me_experience').value=(m.experience||[]).map(x=>[x.title,x.years,x.text].join(' | ')).join('\\n');
 $('#me_training').value=(m.training||[]).join('\\n');
 $('#me_highlights').value=(m.highlights||[]).map(x=>[x.icon,x.title,x.text].join(' | ')).join('\\n');$('#me_skills').value=(m.skills||[]).join(', ');
 $('#me_stats').value=(m.stats||[]).map(x=>x.join(' | ')).join('\\n')}
$('#me_photo').onchange=e=>{const f=e.target.files[0];if(f)$('#me_ph').src=URL.createObjectURL(f)};
$('#meBtn').onclick=async()=>{const fd=new FormData();MEF.forEach(k=>fd.append(k,$('#me_'+k).value));
 ['experience','training','skills','stats','highlights'].forEach(k=>fd.append(k,$('#me_'+k).value));
 const f=$('#me_photo').files[0];if(f)fd.append('photo',f,f.name);
 const j=await post('/admin/api/profile',fd);msg($('#memsg'),j.error||'انحفظ ✓',!j.error);if(!j.error){$('#me_photo').value='';loadMe()}};
load();loadMe();
</script></body></html>''' % STYLE


if __name__ == '__main__':      # local preview: python server.py  (site folder)
    app.run(port=int(os.environ.get('PORT', 8000)), debug=False)
