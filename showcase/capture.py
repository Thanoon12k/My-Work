"""Run a project, crawl it in a headless browser and save screenshots.
Falls back to rendering the project's own templates when the app will not start."""
import hashlib, os, re, shutil, signal, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

IS_WIN = os.name == 'nt'
DEMO_USER, DEMO_EMAIL, DEMO_PASS = 'demo', 'demo@example.com', 'Demo12345!'
ERROR_MARKERS = [
    'Traceback (most recent call last)', 'Page not found (404)', 'Server Error (500)',
    'OperationalError', 'TemplateDoesNotExist', 'ModuleNotFoundError', 'Cannot GET /',
    'Internal Server Error', 'Failed to compile', 'ProgrammingError', 'NoReverseMatch',
    'ImproperlyConfigured', 'The requested URL was not found', 'DisallowedHost',
    'ImportError', 'Module not found', 'Unhandled Runtime Error', 'jinja2.exceptions',
    'Directory listing for /', 'AttributeError at', 'Bad Request (400)',
]
SKIP_LINK = re.compile(r'logout|signout|sign-out|delete|remove|/static/|/media/|\.(pdf|zip|png|'
                       r'jpe?g|gif|svg|webp|avif|ico|css|js|xlsx?|docx?|mp3|mp4)$|^mailto:|^tel:|/admin/.+',
                       re.I)


def log(msg):
    print('    ' + msg, flush=True)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ---------------------------------------------------------------- processes

class Server:
    """A background process that we can wait on and kill with all its children."""

    def __init__(self, cmd, cwd, env=None, logfile=None):
        self.logfile = logfile or tempfile.mktemp(suffix='.log')
        self.fh = open(self.logfile, 'w', encoding='utf-8', errors='replace')
        e = dict(os.environ, **(env or {}))
        kw = dict(cwd=cwd, env=e, stdout=self.fh, stderr=subprocess.STDOUT,
                  stdin=subprocess.DEVNULL)
        if IS_WIN:
            kw['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw['start_new_session'] = True
        self.p = subprocess.Popen(cmd, **kw)

    def tail(self, n=1200):
        try:
            return open(self.logfile, encoding='utf-8', errors='replace').read()[-n:]
        except OSError:
            return ''

    def wait_http(self, url, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if self.p.poll() is not None:
                return False
            try:
                urllib.request.urlopen(url, timeout=5)
                return True
            except urllib.error.HTTPError:
                return True                    # any HTTP answer means it is up
            except Exception:
                time.sleep(1)
        return False

    def stop(self):
        if self.p.poll() is None:
            try:
                if IS_WIN:
                    subprocess.run(['taskkill', '/F', '/T', '/PID', str(self.p.pid)],
                                   capture_output=True)
                else:
                    os.killpg(self.p.pid, signal.SIGTERM)
                    try:
                        self.p.wait(5)
                    except subprocess.TimeoutExpired:
                        os.killpg(self.p.pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
        self.fh.close()


def run(cmd, cwd, timeout, env=None):
    try:
        r = subprocess.run(cmd, cwd=cwd, env=dict(os.environ, **(env or {})),
                           capture_output=True, text=True, timeout=timeout,
                           errors='replace')
        return r.returncode, (r.stdout or '') + (r.stderr or '')
    except (subprocess.TimeoutExpired, OSError) as e:
        return -1, str(e)


# ---------------------------------------------------------------- python envs

def venv_python(envdir):
    return os.path.join(envdir, 'Scripts' if IS_WIN else 'bin',
                        'python.exe' if IS_WIN else 'python')


def python_env(proj_dir, envdir, extra=()):
    """A venv per project (inherits globally installed packages to save time)."""
    py = venv_python(envdir)
    if not os.path.exists(py):
        code, out = run([sys.executable, '-m', 'venv', '--system-site-packages', envdir],
                        proj_dir, 180)
        if code != 0:
            log('venv failed, using system python')
            return sys.executable
    reqs = []
    for d in (proj_dir, os.path.dirname(proj_dir)):
        for fn in ('requirements.txt', 'requirements-dev.txt', 'req.txt'):
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                reqs.append(p)
        if reqs:
            break
    stamp = os.path.join(envdir, '.installed')
    if not os.path.exists(stamp):
        for r in reqs:
            code, out = run([py, '-m', 'pip', 'install', '-q', '--disable-pip-version-check',
                             '-r', r], proj_dir, 900)
            if code != 0:           # one bad pin should not sink the rest
                log('requirements had errors, installing line by line')
                for line in open(r, encoding='utf-8', errors='replace'):
                    line = line.split('#')[0].strip()
                    if line and not line.startswith('-'):
                        run([py, '-m', 'pip', 'install', '-q', '--disable-pip-version-check',
                             line], proj_dir, 300)
        if extra:
            run([py, '-m', 'pip', 'install', '-q', '--disable-pip-version-check', *extra],
                proj_dir, 600)
        open(stamp, 'w').close()
    return py


APP_ENV = {
    'SECRET_KEY': 'showcase-dev-key', 'DJANGO_SECRET_KEY': 'showcase-dev-key',
    'DEBUG': 'True', 'DJANGO_DEBUG': 'True', 'ALLOWED_HOSTS': '*',
    'FLASK_DEBUG': '0', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1',
    'BROWSER': 'none', 'CI': 'true',
}


def start_django(root, where, envdir):
    d = os.path.join(root, where)
    py = python_env(d, envdir, extra=['django'])
    port = free_port()
    env = dict(APP_ENV, DJANGO_SUPERUSER_USERNAME=DEMO_USER,
               DJANGO_SUPERUSER_EMAIL=DEMO_EMAIL, DJANGO_SUPERUSER_PASSWORD=DEMO_PASS)
    run([py, 'manage.py', 'makemigrations', '--noinput'], d, 180, env)
    run([py, 'manage.py', 'migrate', '--noinput', '--run-syncdb'], d, 300, env)
    run([py, 'manage.py', 'createsuperuser', '--noinput'], d, 120, env)
    s = Server([py, 'manage.py', 'runserver', '127.0.0.1:%d' % port, '--noreload',
                '--insecure'], d, env)
    return s, 'http://127.0.0.1:%d/' % port, 90


def start_flask(root, where, envdir):
    f = os.path.join(root, where)
    d, fn = os.path.split(f)
    py = python_env(d, envdir, extra=['flask'])
    port = free_port()
    mod = fn[:-3]
    env = dict(APP_ENV, PORT=str(port), FLASK_RUN_PORT=str(port))
    s = Server([py, '-m', 'flask', '--app', mod, 'run', '--port', str(port),
                '--host', '127.0.0.1'], d, env)
    return s, 'http://127.0.0.1:%d/' % port, 90


def start_fastapi(root, where, envdir):
    f = os.path.join(root, where)
    d, fn = os.path.split(f)
    py = python_env(d, envdir, extra=['fastapi', 'uvicorn'])
    var = re.search(r'(\w+)\s*=\s*FastAPI\(', open(f, encoding='utf-8', errors='replace').read())
    port = free_port()
    s = Server([py, '-m', 'uvicorn', '%s:%s' % (fn[:-3], var.group(1) if var else 'app'),
                '--port', str(port)], d, APP_ENV)
    return s, 'http://127.0.0.1:%d/docs' % port, 90


def start_streamlit(root, where, envdir):
    f = os.path.join(root, where)
    d = os.path.dirname(f)
    py = python_env(d, envdir, extra=['streamlit'])
    port = free_port()
    s = Server([py, '-m', 'streamlit', 'run', f, '--server.port', str(port),
                '--server.headless', 'true'], d, APP_ENV)
    return s, 'http://127.0.0.1:%d/' % port, 120


def start_gradio(root, where, envdir):
    f = os.path.join(root, where)
    d = os.path.dirname(f)
    py = python_env(d, envdir, extra=['gradio'])
    port = free_port()
    s = Server([py, f], d, dict(APP_ENV, GRADIO_SERVER_PORT=str(port),
                                GRADIO_SERVER_NAME='127.0.0.1'))
    return s, 'http://127.0.0.1:%d/' % port, 240


def static_server(directory):
    port = free_port()
    s = Server([sys.executable, '-m', 'http.server', str(port), '--bind', '127.0.0.1',
                '--directory', directory], directory)
    return s, 'http://127.0.0.1:%d/' % port, 20


def start_static(root, where, envdir):
    return static_server(os.path.join(root, where))


def npm_cmd():
    return shutil.which('npm.cmd' if IS_WIN else 'npm') or 'npm'


def start_npm(kind):
    def start(root, where, envdir):
        d = os.path.join(root, where)
        if not os.path.isdir(os.path.join(d, 'node_modules')):
            log('npm install (this can take a few minutes)')
            code, out = run([npm_cmd(), 'install', '--no-audit', '--no-fund',
                             '--loglevel=error', '--legacy-peer-deps'], d, 900)
            if code != 0:
                log('npm install failed: ' + out.strip()[-300:])
        port = free_port()
        env = dict(APP_ENV, PORT=str(port), HOST='127.0.0.1',
                   NODE_OPTIONS='--openssl-legacy-provider' if kind == 'cra' else '')
        npx = shutil.which('npx.cmd' if IS_WIN else 'npx') or 'npx'
        if kind == 'vite':
            cmd = [npx, 'vite', '--port', str(port), '--host', '127.0.0.1', '--strictPort']
        elif kind == 'next':
            cmd = [npx, 'next', 'dev', '-p', str(port)]
        else:
            cmd = [npm_cmd(), 'start']
        return Server(cmd, d, env), 'http://127.0.0.1:%d/' % port, 240
    return start


def start_extension(root, where, envdir):
    import json
    d = os.path.join(root, where)
    m = json.load(open(os.path.join(d, 'manifest.json'), encoding='utf-8-sig'))
    page = ((m.get('action') or m.get('browser_action') or {}).get('default_popup')
            or m.get('options_page') or (m.get('options_ui') or {}).get('page')
            or (m.get('side_panel') or {}).get('default_path'))
    if not page:
        return None
    s, url, t = static_server(d)
    return s, url + page.lstrip('/'), t


def flutter_bin():
    for c in (os.environ.get('FLUTTER'), shutil.which('flutter'), '/opt/flutter/bin/flutter',
              os.path.expanduser('~/flutter/bin/flutter')):
        if c and os.path.exists(c):
            return c
    return None


def flutter_prepare(d, fl, env):
    """Small, local-only tweaks so a phone app can run in a browser for screenshots."""
    pub = os.path.join(d, 'pubspec.yaml')
    spec = open(pub, encoding='utf-8', errors='replace').read()
    # assets listed in pubspec but not committed (.env and friends): use the example or empty
    for a in re.findall(r'^\s*-\s*["\']?([^"\'\s#]+)', spec.split('assets:', 1)[-1], re.M):
        f = os.path.join(d, a)
        if a.endswith('/') or os.path.exists(f) or not re.search(r'(^|/)\.?[\w.-]+$', a):
            continue
        for ex in (f + '.example', f + '.sample', os.path.join(d, '.env.example')):
            if os.path.isfile(ex):
                shutil.copy(ex, f)
                break
        else:
            os.makedirs(os.path.dirname(f) or d, exist_ok=True)
            open(f, 'w').close()
    # sqflite has no web backend: switch it to the wasm build of SQLite
    main = os.path.join(d, 'lib', 'main.dart')
    if re.search(r'^\s+sqflite:', spec, re.M) and 'sqflite_common_ffi_web' not in spec \
            and os.path.isfile(main):
        code, _ = run([fl, 'pub', 'add', 'sqflite_common_ffi_web'], d, 600, env)
        if code == 0:
            run([fl, 'pub', 'run', 'sqflite_common_ffi_web:setup'], d, 600, env)
            src = open(main, encoding='utf-8').read()
            src2 = re.sub(r'(\bmain\s*\([^)]*\)\s*(?:async\s*)?\{)',
                          r'\1\n  sc_sql.databaseFactory = sc_web.databaseFactoryFfiWeb;',
                          src, count=1)
            if src2 != src:
                src2 = ("import 'package:sqflite/sqflite.dart' as sc_sql;\n"
                        "import 'package:sqflite_common_ffi_web/sqflite_ffi_web.dart' as sc_web;\n"
                        + src2)
                open(main, 'w', encoding='utf-8').write(src2)


def start_flutter(root, where, envdir):
    """Build the Flutter app for the web and serve the result: real UI, not a mockup."""
    fl = flutter_bin()
    if not fl:
        log('flutter SDK not found (set FLUTTER=/path/to/flutter) - using mockups')
        return None
    d = os.path.join(root, where)
    web = os.path.join(d, 'build', 'web')
    stamp = os.path.join(web, 'main.dart.js')
    if not os.path.exists(stamp):
        env = {'CI': 'true', 'FLUTTER_SUPPRESS_ANALYTICS': 'true'}
        if not os.path.isdir(os.path.join(d, 'web')):
            run([fl, 'create', '--platforms=web', '.'], d, 300, env)
        code, out = run([fl, 'pub', 'get'], d, 600, env)
        flutter_prepare(d, fl, env)
        if code != 0:
            log('pub get failed, trying pub upgrade --major-versions')
            run([fl, 'pub', 'upgrade', '--major-versions'], d, 600, env)
        log('flutter build web (about a minute)')
        code, out = run([fl, 'build', 'web', '--release', '--no-web-resources-cdn',
                         '--no-wasm-dry-run'], d, 900, env)
        if code != 0 or not os.path.exists(stamp):
            err = [l for l in out.splitlines() if 'Error' in l or 'error' in l][:3]
            log('flutter web build failed: ' + ' | '.join(err)[:300])
            return None
    s, url, t = static_server(web)
    return s, url, t


STARTERS = {
    'django': start_django, 'flask': start_flask, 'fastapi': start_fastapi,
    'streamlit': start_streamlit, 'gradio': start_gradio, 'static': start_static,
    'extension': start_extension, 'vite': start_npm('vite'), 'cra': start_npm('cra'),
    'next': start_npm('next'), 'node': start_npm('node'), 'flutter': start_flutter,
}


# ---------------------------------------------------------------- browser

class Browser:
    def __init__(self):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        exe = os.environ.get('CHROMIUM_PATH')
        try:
            self.b = self.pw.chromium.launch(executable_path=exe) if exe else \
                self.pw.chromium.launch()
        except Exception:
            fallback = '/opt/pw-browsers/chromium'
            if not os.path.exists(fallback):
                raise SystemExit('! no browser. Run:  python -m playwright install chromium')
            self.b = self.pw.chromium.launch(executable_path=fallback)

    def page(self, w=1440, h=900, scale=1, mobile=False):
        ctx = self.b.new_context(viewport={'width': w, 'height': h}, device_scale_factor=scale,
                                 is_mobile=mobile, has_touch=mobile, ignore_https_errors=True,
                                 locale='ar-IQ')
        ctx.set_default_timeout(20000)
        return ctx.new_page()

    def html_shot(self, html, out, w=1280, h=800, scale=1.5, base_dir=None):
        """Render an HTML string to a PNG (used for mockups)."""
        pg = self.page(w, h, scale)
        try:
            if base_dir:
                tmp = os.path.join(base_dir, '_render.html')
                open(tmp, 'w', encoding='utf-8').write(html)
                pg.goto('file://' + os.path.abspath(tmp).replace('\\', '/'))
            else:
                pg.set_content(html, wait_until='load')
            try:
                pg.wait_for_load_state('networkidle', timeout=8000)
                pg.evaluate('''Promise.all([document.fonts.load("22px 'Material Icons Round'"),
                    document.fonts.load("700 20px Cairo"), document.fonts.load("20px Cairo")])
                    .then(() => document.fonts.ready)''')
            except Exception:
                pass
            pg.wait_for_timeout(400)
            pg.screenshot(path=out)
        finally:
            pg.context.close()

    def close(self):
        try:
            self.b.close()
            self.pw.stop()
        except Exception:
            pass


def looks_broken(pg):
    try:
        text = pg.inner_text('body', timeout=3000)
    except Exception:
        return 'no body'
    for m in ERROR_MARKERS:
        if m in text[:4000]:
            return m
    visuals = pg.evaluate("document.querySelectorAll('img,canvas,svg,video,input,button').length")
    if len(text.strip()) < 15 and visuals < 2:
        return 'blank page'
    return None


def settle(pg):
    try:
        pg.wait_for_load_state('networkidle', timeout=12000)
    except Exception:
        pass
    pg.wait_for_timeout(1200)


def try_login(pg):
    """Fill a login form with the demo account we created."""
    try:
        pw = pg.query_selector('input[type=password]')
        if not pw or not pw.is_visible():
            return False
        user = pg.query_selector('input[type=email], input[name*=user i], input[name*=email i], '
                                 'input[name*=phone i], input[type=text], input[type=tel]')
        if user and user.is_visible():
            t = (user.get_attribute('type') or '') + (user.get_attribute('name') or '')
            user.fill(DEMO_EMAIL if 'email' in t.lower() else DEMO_USER)
        pw.fill(DEMO_PASS)
        before = pg.url
        pw.press('Enter')
        pg.wait_for_timeout(2500)
        settle(pg)
        ok = pg.url != before and not pg.query_selector('input[type=password]')
        return ok
    except Exception:
        return False


def same_origin_links(pg, base):
    try:
        hrefs = pg.eval_on_selector_all('a[href]', 'els => els.map(e => e.href)')
    except Exception:
        return []
    out = []
    for h in hrefs:
        h = h.split('#')[0]
        if h.startswith(base) and not SKIP_LINK.search(h) and h not in out:
            out.append(h)
    return out


def crawl(browser, url, outdir, prefix, max_pages=5, mobile=True, clip_height=900):
    """Screenshot the start page and a few linked pages. Returns shot records."""
    shots, seen_hashes = [], set()
    base = re.match(r'https?://[^/]+/', url).group(0)
    pg = browser.page(1440, clip_height)
    queue, done, logged_in = [url], set(), False

    def save(p, name, caption, device):
        data = p.screenshot()
        h = hashlib.md5(data).hexdigest()
        if h in seen_hashes:
            return
        seen_hashes.add(h)
        path = os.path.join(outdir, name)
        open(path, 'wb').write(data)
        shots.append({'file': name, 'kind': 'live', 'device': device, 'caption': caption})

    try:
        while queue and len(shots) < max_pages:
            u = queue.pop(0)
            if u in done:
                continue
            done.add(u)
            try:
                pg.goto(u, wait_until='domcontentloaded', timeout=30000)
            except Exception as e:
                log('  %s: %s' % (u, str(e).splitlines()[0][:80]))
                continue
            settle(pg)
            bad = looks_broken(pg)
            if bad:
                log('  skip %s (%s)' % (u[len(base) - 1:] or '/', bad))
                continue
            title = (pg.title() or '').strip()[:60]
            save(pg, '%s%02d.png' % (prefix, len(shots) + 1), title, 'desktop')
            if not logged_in and pg.query_selector('input[type=password]'):
                if try_login(pg):
                    logged_in = True
                    log('  logged in with demo account')
                    queue.insert(0, pg.url)
                    done.discard(pg.url)
            for link in same_origin_links(pg, base):
                if link not in done and link not in queue:
                    queue.append(link)
        if shots and mobile:
            m = browser.page(390, 844, 2, mobile=True)
            try:
                m.goto(url, wait_until='domcontentloaded', timeout=30000)
                settle(m)
                if not looks_broken(m):
                    save(m, '%smobile.png' % prefix, 'Mobile', 'mobile')
            except Exception:
                pass
            finally:
                m.context.close()
    finally:
        pg.context.close()
    return shots


def _img_diff(a, b):
    """0..1 share of pixels that differ noticeably between two PNG byte strings."""
    import io
    from PIL import Image, ImageChops
    ia = Image.open(io.BytesIO(a)).convert('L').resize((103, 223))
    ib = Image.open(io.BytesIO(b)).convert('L').resize((103, 223))
    d = ImageChops.difference(ia, ib).point(lambda v: 255 if v > 24 else 0)
    return sum(1 for v in d.getdata() if v) / (103 * 223)


def _blank(data):
    import io
    from PIL import Image, ImageStat
    im = Image.open(io.BytesIO(data)).convert('L')
    return max(ImageStat.Stat(im).stddev) < 6


FLUTTER_ERRORS = re.compile(r'Bad state|Exception|Error:|MissingPluginException|'
                            r'Unsupported operation|LateInitializationError|تعذّ?ر تشغيل', re.I)

TAPPABLES_JS = """() => {
  const vw = innerWidth, vh = innerHeight, seen = new Set();
  return [...document.querySelectorAll('flt-semantics')]
    .filter(e => ['button','tab','link','menuitem'].includes(e.getAttribute('role'))
                 || e.hasAttribute('flt-tappable'))
    .map(e => { const r = e.getBoundingClientRect();
                return {x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height,
                        label: (e.getAttribute('aria-label') || e.innerText || '').trim()}; })
    .filter(o => o.w > 8 && o.h > 8 && o.x > 0 && o.y > 56 && o.x < vw && o.y < vh
                 && !/(log ?out|sign ?out|خروج|حذف|delete|remove)/i.test(o.label))
    .filter(o => { const k = Math.round(o.x / 20) + ':' + Math.round(o.y / 20);
                   if (seen.has(k)) return false; seen.add(k); return true; });
}"""


def flutter_shots(browser, url, outdir, max_shots=5):
    """Open a Flutter web build at phone size, wait past the splash, tap around."""
    pg = browser.page(412, 892, 2, mobile=True)
    shots, kept = [], []

    def keep(data, caption):
        if _blank(data) or any(_img_diff(data, k) < 0.03 for k in kept):
            return False
        name = 'live%02d.png' % (len(shots) + 1)
        open(os.path.join(outdir, name), 'wb').write(data)
        kept.append(data)
        shots.append({'file': name, 'kind': 'live', 'device': 'mobile', 'caption': caption})
        return True

    def load():
        pg.goto(url, wait_until='load', timeout=60000)
        first = None
        for i in range(8):                      # let splash screens / animations finish
            pg.wait_for_timeout(2500)
            if i == 1:
                first = pg.screenshot()
        return first, pg.screenshot()

    try:
        first, home = load()
        try:
            pg.evaluate("document.querySelector('flt-semantics-placeholder')?.click()")
            pg.wait_for_timeout(800)
            text = pg.evaluate("[...document.querySelectorAll('flt-semantics')]"
                               ".map(e => e.getAttribute('aria-label') || e.innerText || '')"
                               ".join(' ')")
            taps = pg.evaluate(TAPPABLES_JS)[:10]
        except Exception:
            text, taps = '', []
        bad = FLUTTER_ERRORS.search(text or '')
        if bad:
            log('  app shows an error screen (%s) - not using it' % bad.group(0))
            return []
        if first and _img_diff(first, home) > 0.15:
            keep(first, 'Splash')
        if not keep(home, 'Home') and not kept:
            return []
        for t in taps:
            if len(shots) >= max_shots:
                break
            try:
                pg.mouse.click(t['x'], t['y'])
                pg.wait_for_timeout(2500)
                data = pg.screenshot()
                if _img_diff(data, home) > 0.08:
                    keep(data, t['label'][:40] or 'Screen')
                pg.go_back()
                pg.wait_for_timeout(1500)
                if _img_diff(pg.screenshot(), home) > 0.08:
                    first, home = load()
                    pg.evaluate("document.querySelector('flt-semantics-placeholder')?.click()")
                    pg.wait_for_timeout(800)
            except Exception:
                continue
    finally:
        pg.context.close()
    return shots


def capture_live(browser, project, repo_dir, outdir, envroot, max_pages=5):
    kind = project['primary']
    starter = STARTERS.get(kind)
    if not starter:
        return []
    where = project['where'][kind]
    envdir = os.path.join(envroot, project['slug'])
    try:
        started = starter(repo_dir, where, envdir)
    except Exception as e:
        log('could not start: %s' % e)
        return []
    if not started:
        return []
    server, url, timeout = started
    try:
        log('starting %s at %s' % (kind, url))
        if not server.wait_http(url, timeout):
            log('did not come up. log tail:\n      ' +
                server.tail(600).replace('\n', '\n      '))
            return []
        time.sleep(1)
        if kind == 'extension':
            pg = browser.page(420, 600, 2)
            try:
                pg.goto(url)
                settle(pg)
                if looks_broken(pg):
                    return []
                pg.screenshot(path=os.path.join(outdir, 'live01.png'))
                return [{'file': 'live01.png', 'kind': 'live', 'device': 'popup',
                         'caption': 'Extension popup'}]
            finally:
                pg.context.close()
        if kind == 'flutter':
            return flutter_shots(browser, url, outdir)
        return crawl(browser, url, outdir, 'live', max_pages=max_pages)
    finally:
        server.stop()


# ---------------------------------------------------------------- template fallback

DJ_TAG_DROP = re.compile(r'{%-?\s*(load|csrf_token|now|cycle|firstof|spaceless|endspaceless|'
                         r'autoescape|endautoescape|widthratio|trans|blocktrans|endblocktrans|'
                         r'translate|blocktranslate|endblocktranslate|get_current_language|'
                         r'regroup|lorem|verbatim|endverbatim|debug|templatetag|localize|'
                         r'endlocalize|language|endlanguage|timezone|endtimezone|'
                         r'get_available_languages|render_field|bootstrap\w*|crispy|\w+_tags?)'
                         r'\b[^%]*-?%}')


def django_to_jinja(src):
    src = re.sub(r'{%\s*comment\s*%}.*?{%\s*endcomment\s*%}', '', src, flags=re.S)
    src = re.sub(r'{#.*?#}', '', src, flags=re.S)
    src = re.sub(r'''{%\s*static\s+['"]([^'"]+)['"][^%]*%}''', r'/static/\1', src)
    src = re.sub(r'''{%\s*trans(?:late)?\s+['"]([^'"]*)['"][^%]*%}''', r'\1', src)
    src = re.sub(r'{%\s*url\s[^%]*%}', '#', src)
    src = re.sub(r'{%\s*empty\s*%}', '{% else %}', src)
    src = re.sub(r'{%\s*ifequal\s+(\S+)\s+(\S+)\s*%}', r'{% if \1 == \2 %}', src)
    src = re.sub(r'{%\s*endifequal\s*%}', '{% endif %}', src)
    src = DJ_TAG_DROP.sub('', src)
    # |date:"Y" -> |date("Y")
    src = re.sub(r'\|(\w+):("[^"]*"|\'[^\']*\'|[\w.]+)', r'|\1(\2)', src)
    # "x.0" style subscripts and method calls without parens are fine in jinja
    return src


def render_templates(project, repo_dir, outdir, browser, limit=4):
    """Render the app's own HTML templates with empty data and screenshot them."""
    import jinja2
    tpl_dirs, static_dirs = [], []
    for d, dirs, files in os.walk(repo_dir):
        dirs[:] = [x for x in dirs if x not in ('node_modules', '.git', 'venv', '.venv',
                                                '__pycache__', 'site-packages', 'out')
                   and not os.path.exists(os.path.join(d, x, '.git'))]
        base = os.path.basename(d)
        if base == 'templates':
            tpl_dirs.append(d)
        elif base == 'static':
            static_dirs.append(d)
    if not tpl_dirs:
        return []
    django = project['primary'] == 'django'

    class Loader(jinja2.BaseLoader):
        def get_source(self, env, name):
            for td in tpl_dirs:
                p = os.path.join(td, name)
                if os.path.isfile(p):
                    src = open(p, encoding='utf-8', errors='replace').read()
                    return (django_to_jinja(src) if django else src), p, lambda: True
            raise jinja2.TemplateNotFound(name)

    env = jinja2.Environment(loader=Loader(), undefined=jinja2.ChainableUndefined,
                             extensions=['jinja2.ext.do', 'jinja2.ext.loopcontrols'])

    class Any(dict):
        def __missing__(self, k):
            return lambda *a, **kw: (a[0] if a else '')

    env.filters = Any(env.filters)
    env.tests = Any(env.tests)
    g = {'url_for': lambda ep, **kw: ('/static/' + kw.get('filename', '')) if ep == 'static'
         else '#', 'get_flashed_messages': lambda *a, **k: [], 'csrf_token': lambda: '',
         'static': lambda p: '/static/' + p, '_': lambda s, *a: s, 'gettext': lambda s: s,
         'request': {'path': '/', 'args': {}}, 'session': {}, 'config': {},
         'current_user': {'is_authenticated': True, 'username': DEMO_USER}}
    env.globals.update(g)

    names = []
    for td in tpl_dirs:
        for d, _, files in os.walk(td):
            for fn in files:
                if not fn.endswith('.html'):
                    continue
                rel = os.path.relpath(os.path.join(d, fn), td).replace('\\', '/')
                low = rel.lower()
                if re.search(r'(^|/)(_|base|layout|master|partials?/|includes?/|components?/|'
                             r'emails?/|registration/password|admin/)', low) or 'email' in low:
                    continue
                size = os.path.getsize(os.path.join(d, fn))
                score = size + (100000 if re.search(r'(index|home|dashboard|landing)', low) else 0)
                names.append((score, rel))
    names = [n for _, n in sorted(names, reverse=True)]

    work = tempfile.mkdtemp(prefix='tpl_')
    sroot = os.path.join(work, 'static')
    for sd in static_dirs:
        shutil.copytree(sd, sroot, dirs_exist_ok=True)
    rendered = []
    for n in names:
        if len(rendered) >= limit:
            break
        try:
            html = env.get_template(n).render()
        except Exception:
            try:     # last resort: strip every tag and show the raw markup
                raw = open(next(os.path.join(td, n) for td in tpl_dirs
                                if os.path.isfile(os.path.join(td, n))),
                           encoding='utf-8', errors='replace').read()
                if '{% extends' in raw:
                    continue
                html = re.sub(r'{%.*?%}|{{.*?}}|{#.*?#}', '', raw, flags=re.S)
            except Exception:
                continue
        if len(re.sub(r'<[^>]+>|\s', '', html)) < 20:
            continue
        fn = 'p%d.html' % len(rendered)
        open(os.path.join(work, fn), 'w', encoding='utf-8').write(html)
        rendered.append((fn, n))
    shots = []
    if rendered:
        server, url, t = static_server(work)
        try:
            server.wait_http(url, t)
            pg = browser.page(1440, 900)
            try:
                for fn, n in rendered:
                    try:
                        pg.goto(url + fn, wait_until='domcontentloaded')
                        settle(pg)
                    except Exception:
                        continue
                    if looks_broken(pg):
                        continue
                    out = 'tpl%02d.png' % (len(shots) + 1)
                    pg.screenshot(path=os.path.join(outdir, out))
                    shots.append({'file': out, 'kind': 'template', 'device': 'desktop',
                                  'caption': n})
            finally:
                pg.context.close()
        finally:
            server.stop()
    shutil.rmtree(work, ignore_errors=True)
    return shots
