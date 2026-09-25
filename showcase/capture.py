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


STARTERS = {
    'django': start_django, 'flask': start_flask, 'fastapi': start_fastapi,
    'streamlit': start_streamlit, 'gradio': start_gradio, 'static': start_static,
    'extension': start_extension, 'vite': start_npm('vite'), 'cra': start_npm('cra'),
    'next': start_npm('next'), 'node': start_npm('node'),
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
                                                '__pycache__', 'site-packages')]
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
