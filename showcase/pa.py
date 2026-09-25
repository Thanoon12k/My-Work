"""Upload the built site to PythonAnywhere and point the account's web app at it.
Token comes from $PA_TOKEN (or a .pa_token file next to config.json) — never commit it."""
import json, mimetypes, os, sys, urllib.error, urllib.parse, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor

HOST = os.environ.get('PA_HOST', 'www.pythonanywhere.com')

WSGI = '''import os, sys
os.environ['SHOWCASE_ROOT'] = %(root)r
os.environ['SHOWCASE_DATA'] = %(data)r
if %(root)r not in sys.path:
    sys.path.insert(0, %(root)r)
from server import app as application
'''


class PA:
    def __init__(self, user, token):
        self.user, self.token = user, token
        self.api = 'https://%s/api/v0/user/%s' % (HOST, user)

    def call(self, method, path, data=None, ctype=None):
        h = {'Authorization': 'Token ' + self.token}
        if isinstance(data, dict):
            data = urllib.parse.urlencode(data).encode()
            ctype = 'application/x-www-form-urlencoded'
        if ctype:
            h['Content-Type'] = ctype
        req = urllib.request.Request(self.api + path, data=data, headers=h, method=method)
        import re, time
        for attempt in range(12):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return r.status, r.read().decode('utf-8', 'replace')
            except urllib.error.HTTPError as e:
                body = e.read().decode('utf-8', 'replace')
                if e.code in (429, 502, 503, 504) and attempt < 11:
                    # PythonAnywhere says how long to wait: "Expected available in 42 seconds"
                    m = re.search(r'available in (\d+) second', body)
                    time.sleep(int(m.group(1)) + 1 if m else 2 ** min(attempt + 1, 5))
                    continue
                return e.code, body
            except urllib.error.URLError as e:
                if attempt >= 3:
                    return 0, str(e.reason)
                time.sleep(3)

    def upload(self, remote, blob):
        b = uuid.uuid4().hex
        name = os.path.basename(remote)
        ct = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        body = ('--%s\r\nContent-Disposition: form-data; name="content"; filename="%s"\r\n'
                'Content-Type: %s\r\n\r\n' % (b, name, ct)).encode() + blob + \
            ('\r\n--%s--\r\n' % b).encode()
        return self.call('POST', '/files/path' + urllib.parse.quote(remote), body,
                         'multipart/form-data; boundary=' + b)


def token_for(cfg):
    t = os.environ.get('PA_TOKEN', '').strip()
    p = os.path.join(os.path.dirname(cfg['_out']), '.pa_token')
    if not t and os.path.isfile(p):
        t = open(p, encoding='utf-8').read().strip()
    if not t:
        sys.exit('! set PA_TOKEN (https://www.pythonanywhere.com/account/#api_token)')
    return t


def deploy(cfg, user=None):
    d = cfg.get('deploy', {})
    user = user or d.get('user')
    if not user:
        sys.exit('! no PythonAnywhere user (config deploy.user or --user)')
    pa = PA(user, token_for(cfg))
    site = os.path.join(cfg['_out'], 'site')
    if not os.path.isfile(os.path.join(site, 'index.html')):
        sys.exit('! build the site first: python -m showcase build')
    root = '/home/%s/%s' % (user, d.get('remote_dir', 'portfolio'))
    data_dir = root + '_data'          # admin uploads + edits: never deleted
    domain = d.get('domain') or '%s.pythonanywhere.com' % user

    print('==> token')
    c, b = pa.call('GET', '/cpu/')
    if c != 200:
        sys.exit('! token rejected for %s (HTTP %s): %s' % (user, c, b[:200]))

    for old in d.get('remove_old', []):
        c, _ = pa.call('DELETE', '/files/path/home/%s/%s' % (user, old))
        print('    removed /home/%s/%s (HTTP %s)' % (user, old, c))

    files = []
    for dp, _, fs in os.walk(site):
        for f in fs:
            lp = os.path.join(dp, f)
            files.append((lp, root + '/' + os.path.relpath(lp, site).replace(os.sep, '/')))
    print('==> uploading %d files' % len(files))
    failed = []

    def up(item):
        lp, rp = item
        c, b = pa.upload(rp, open(lp, 'rb').read())
        if c not in (200, 201):
            failed.append((rp, c, b[:120]))

    with ThreadPoolExecutor(3) as ex:
        for i, _ in enumerate(ex.map(up, files), 1):
            if i % 25 == 0 or i == len(files):
                print('    %d/%d' % (i, len(files)))
    if failed:
        for f in failed[:10]:
            print('   ! %s -> %s %s' % f)
        sys.exit('! %d uploads failed' % len(failed))

    print('==> web app')
    c, b = pa.call('GET', '/webapps/')
    apps = [w['domain_name'] for w in json.loads(b)] if c == 200 else []
    if domain not in apps:
        for v in ('3.12', '3.11', '3.10', '3.13'):
            c, b = pa.call('POST', '/webapps/', {'domain_name': domain, 'python_version': v})
            if c in (200, 201):
                break
        else:
            sys.exit('! could not create web app %s: %s' % (domain, b[:200]))
    pa.call('PATCH', '/webapps/%s/' % domain, {'source_directory': root,
                                               'force_https': 'true'})
    wsgi = '/var/www/%s_wsgi.py' % domain.replace('.', '_')
    c, b = pa.upload(wsgi, (WSGI % {'root': root, 'data': data_dir}).encode())
    if c not in (200, 201):
        sys.exit('! WSGI write failed (HTTP %s): %s' % (c, b[:200]))
    # images straight from PythonAnywhere's static server (no Python involved)
    c, b = pa.call('GET', '/webapps/%s/static_files/' % domain)
    maps = json.loads(b) if c == 200 else []
    want = {'/img/': root + '/img', '/u/': data_dir + '/uploads'}
    for m in maps:
        if m['url'] in want and m['path'] != want[m['url']]:
            pa.call('DELETE', '/webapps/%s/static_files/%s/' % (domain, m['id']))
        elif m['url'] in want:
            want.pop(m['url'])
    for url, path in want.items():
        pa.call('POST', '/webapps/%s/static_files/' % domain, {'url': url, 'path': path})

    # admin password: created once, only its hash is stored on the server
    new_pw = None
    c, _ = pa.call('GET', '/files/path%s/admin.json' % data_dir)
    if c == 404:
        import hashlib, secrets
        salt = secrets.token_hex(16)
        hash_pw = lambda pw: 'pbkdf2$%s$%s' % (salt, hashlib.pbkdf2_hmac(
            'sha256', pw.encode(), salt.encode(), 200_000).hex())   # same as server.hash_pw
        new_pw = secrets.token_urlsafe(9)
        pa.upload(data_dir + '/admin.json', json.dumps(
            {'password': hash_pw(new_pw), 'secret': secrets.token_hex(32)}).encode())
    pa.upload(data_dir + '/uploads/.keep', b'')

    print('==> reload')
    c, b = pa.call('POST', '/webapps/%s/reload/' % domain, {})
    if c not in (200, 201):
        sys.exit('! reload failed (HTTP %s): %s' % (c, b[:200]))
    print('\n  LIVE : https://%s' % domain)
    print('  ADMIN: https://%s/admin' % domain)
    if new_pw:
        print('  admin password (shown once, change it from /admin): %s' % new_pw)
