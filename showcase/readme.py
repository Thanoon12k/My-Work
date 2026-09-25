"""Generate a GitHub README (+ images) that showcases every project.

GitHub strips CSS, so "responsive" here means: images sized in % so rows shrink on a
phone, <picture> for light/dark banners, and short lines that wrap cleanly."""
import html, json, os, shutil, subprocess, sys, time

from .site import CATS, KIND_LABEL

CAT_EN = {'web': ('🌐', 'Web'), 'mobile': ('📱', 'Mobile'), 'desktop': ('🖥️', 'Desktop'),
          'hw': ('🔌', 'Hardware & IoT'), 'ai': ('🤖', 'AI'), 'sim': ('🛰️', 'Networks & Simulation'),
          'tools': ('🧰', 'Tools'), 'docs': ('📚', 'Research & Notes')}
KIND_EN = {'live': 'live screenshot', 'upload': 'live screenshot', 'template': 'rendered templates',
           'repo': 'repo images', 'mockup': 'mock-up from source', 'cover': 'cover art'}
E = html.escape

BANNER = '''<div class="b"><div class="dots"></div>
<div class="logo"><img src="%s"></div>
<div class="t"><small>%s</small><h1>%s</h1><h2>%s</h2>
<p>%d projects — web, mobile, desktop, AI &amp; hardware · Mosul, Iraq</p></div></div>'''
BANNER_CSS = '''
.b{position:relative;width:1280px;height:360px;background:%(bg)s;display:flex;align-items:center;gap:56px;
 padding:0 80px;overflow:hidden}
.b .dots{background-image:radial-gradient(%(ink)s22 1.5px,transparent 1.5px)}
.logo{width:230px;height:230px;flex:none;position:relative}
.logo img{width:100%%;height:100%%;object-fit:cover;border-radius:36px;border:4px solid %(ink)s;
 box-shadow:-10px 10px 0 %(ink)s}
.t h2{font-size:30px;font-weight:800;color:%(dim)s;margin-bottom:8px}
.t small{display:inline-block;border:3px solid %(ink)s;border-radius:40px;padding:2px 16px;font-weight:800;
 font-size:16px;color:%(ink)s;background:%(card)s}
.t h1{font-size:60px;font-weight:900;line-height:1.15;margin:12px 0 2px;color:%(ink)s}
.t p{font-size:21px;line-height:1.6;color:%(dim)s}
'''


def render_banner(browser, me, photo, n, out_light, out_dark):
    import base64
    from .mockup import page
    uri = 'data:image/jpeg;base64,' + base64.b64encode(open(photo, 'rb').read()).decode()
    for path, theme in ((out_light, dict(bg='#FFF6EA', ink='#16130D', dim='#5C554A', card='#fff')),
                        (out_dark, dict(bg='#16130D', ink='#FFF6EA', dim='#D7CDBE',
                                        card='#221E17'))):
        body = BANNER % (uri, E(me.get('role_en', 'Developer')), E(me.get('name_en', '')),
                         E(me.get('name', '')), n)
        browser.html_shot(page(body, BANNER_CSS % theme, w=1280, h=360, bg=theme['bg']),
                          path, w=1280, h=360, scale=1.5)


def site_screenshot(browser, site_dir, out):
    port = 8799
    srv = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '--directory',
                            site_dir], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        pg = browser.page(1280, 1400, 1)
        pg.goto('http://127.0.0.1:%d/' % port)
        pg.wait_for_timeout(3500)
        pg.screenshot(path=out)
        pg.context.close()
        m = browser.page(390, 844, 2, mobile=True)
        m.goto('http://127.0.0.1:%d/' % port)
        m.wait_for_timeout(3000)
        m.screenshot(path=out.replace('.png', '-mobile.png'))
        m.context.close()
    finally:
        srv.kill()


def build(cfg, dest):
    from PIL import Image
    from .capture import Browser
    site = os.path.join(cfg['_out'], 'site')
    data = json.load(open(os.path.join(site, 'data.json'), encoding='utf-8'))
    s = cfg['site']
    live_url = cfg.get('deploy', {}).get('domain') or \
        '%s.pythonanywhere.com' % cfg.get('deploy', {}).get('user', '')
    live_url = 'https://' + live_url
    docs = os.path.join(dest, 'docs')
    shots = os.path.join(docs, 'projects')
    shutil.rmtree(shots, ignore_errors=True)
    os.makedirs(shots)

    # one uniform 16:10 card per project so the grid lines up
    for p in data:
        im = Image.open(os.path.join(site, p['thumb'])).convert('RGB')
        W, H = 640, 400
        if im.height > im.width * 1.2:          # phone screenshot: centre it on a card
            card = Image.new('RGB', (W, H), '#EFE6D8')
            ph = im.resize((round(im.width * H / im.height), H))
            card.paste(ph, ((W - ph.width) // 2, 0))
            im = card
        else:
            scale = W / im.width
            im = im.resize((W, round(im.height * scale)))
            im = im.crop((0, 0, W, H)) if im.height >= H else \
                _pad(im, W, H)
        im.save(os.path.join(shots, p['slug'] + '.webp'), 'WEBP', quality=78)

    b = Browser()
    try:
        me = cfg.get('profile', {})
        render_banner(b, me, os.path.join(os.path.dirname(cfg['_out']), me.get('photo', '')),
                      len(data),
                      os.path.join(docs, 'banner-light.png'), os.path.join(docs, 'banner-dark.png'))
        site_screenshot(b, site, os.path.join(docs, 'site.png'))
    finally:
        b.close()
    for f in ('site.png', 'site-mobile.png'):
        p = os.path.join(docs, f)
        Image.open(p).convert('RGB').save(p.replace('.png', '.webp'), 'WEBP', quality=80)
        os.remove(p)

    open(os.path.join(dest, 'README.md'), 'w', encoding='utf-8').write(
        readme(data, s, live_url, cfg.get('profile', {})))
    print('README + %d project images -> %s' % (len(data), dest))


def _pad(im, W, H):
    from PIL import Image
    c = Image.new('RGB', (W, H), '#EFE6D8')
    c.paste(im, (0, 0))
    return c


def cell(p, width):
    link = p.get('repo') or '#'
    alt = E(p['en'] or p['title'])
    return ('<a href="%s" title="%s"><img src="docs/projects/%s.webp" width="%s" alt="%s"></a>'
            % (link, E(p['title']), p['slug'], width, alt))


def about(me):
    if not me:
        return ''
    out = ['\n## 👋 About me\n']
    out.append('<p dir="rtl">%s</p>\n' % E(me.get('bio', '')))
    if me.get('location'):
        out.append('<p dir="rtl">📍 %s</p>\n' % E(me['location']))
    if me.get('experience'):
        out.append('### 💼 الخبرة · Experience\n')
        for x in me['experience']:
            out.append('- **%s** · <sub>%s</sub><br><sub dir="auto">%s</sub>'
                       % (E(x['title']), E(x['years']), E(x['text'])))
    if me.get('education'):
        out.append('\n🎓 **%s**\n' % E(me['education']))
    for t in me.get('training', []):
        out.append('- %s' % E(t))
    if me.get('skills'):
        out.append('\n<p>%s</p>' % ' '.join(
            '<img src="https://img.shields.io/badge/%s-16130D?style=flat-square" alt="%s">'
            % (_badge(x), E(x)) for x in me['skills']))
    if me.get('languages'):
        out.append('\n🗣️ %s' % E(me['languages']))
    return '\n'.join(out) + '\n\n---\n'


def _badge(x):
    import urllib.parse
    return urllib.parse.quote(x.replace('-', '--').replace('_', '__').replace(' ', '_'), safe='')


def readme(data, s, live_url, me=None):
    by = {}
    for p in data:
        by.setdefault(p['cat'], []).append(p)
    real = sum(1 for p in data if p['kind'] in ('live', 'upload', 'template', 'repo'))
    out = []
    w = out.append
    w('<div align="center">\n')
    w('<a href="%s"><picture>' % live_url)
    w('<source media="(prefers-color-scheme: dark)" srcset="docs/banner-dark.png">')
    w('<img src="docs/banner-light.png" width="100%%" alt="%s"></picture></a>\n'
      % E((me or {}).get('name_en', 'Portfolio')))
    w('<a href="%s"><img src="https://img.shields.io/badge/Live_site-make1it.pythonanywhere.com-FFC93C'
      '?style=for-the-badge&labelColor=16130D" alt="Live site"></a>' % live_url)
    w('<br><img src="https://img.shields.io/badge/projects-%d-12B99C?style=flat-square" alt="">'
      % len(data))
    w(' <img src="https://img.shields.io/badge/real_screenshots-%d-4361EE?style=flat-square" alt="">'
      % real)
    w(' <img src="https://img.shields.io/badge/categories-%d-FF5C39?style=flat-square" alt="">'
      % len(by))
    if s.get('whatsapp'):
        w(' <a href="%s"><img src="https://img.shields.io/badge/WhatsApp-contact-25D366?style=flat-square'
          '&logo=whatsapp&logoColor=white" alt="WhatsApp"></a>' % s['whatsapp'])
    if (me or {}).get('email'):
        w(' <a href="mailto:%s"><img src="https://img.shields.io/badge/Email-%s-EA4335?style=flat-square'
          '&logo=gmail&logoColor=white" alt="Email"></a>' % (me['email'], _badge(me['email'])))
    w('\n\n<p dir="rtl"><b>%s</b></p>\n' % E(s['tagline']))
    w('</div>\n\n---\n')
    w(about(me or {}))

    # featured
    feat = [p for p in data if p.get('featured', 99) < 99][:6] or data[:6]
    w('\n## ⭐ Featured\n')
    w('\n<p align="center">\n%s\n</p>\n' % '\n'.join(cell(p, '49%') for p in feat))
    w('')
    for p in feat:
        w('- %s **[%s](%s)**%s — %s' % (
            CAT_EN[p['cat']][0], E(p['title']), p.get('repo') or live_url,
            ' <sub>%s</sub>' % E(p['en']) if p['en'] and p['en'] != p['title'] else '',
            ' · '.join('`%s`' % E(x) for x in p['stack'][:4]) or '—'))
    w('\n\n---\n\n## 📂 All projects\n')
    w('\n> Tap any picture to open its code. The live site has the full galleries: '
      '**[%s](%s)**\n' % (live_url.replace('https://', ''), live_url))
    for cat, _ in CATS:
        ps = by.get(cat)
        if not ps:
            continue
        icon, name = CAT_EN[cat]
        w('\n<details%s>\n<summary><h3>%s %s — %d</h3></summary>\n'
          % (' open' if cat in ('web', 'mobile', 'hw') else '', icon, name, len(ps)))
        w('\n<p align="center">\n%s\n</p>\n' % '\n'.join(cell(p, '32%') for p in ps))
        w('')
        for p in ps:
            desc = p['desc'] or ''
            if len(desc) > 140:
                desc = desc[:137].rsplit(' ', 1)[0] + '…'
            w('- **[%s](%s)**%s — %s%s' % (
                E(p['title']), p.get('repo') or live_url,
                ' <sub>%s</sub>' % E(p['en']) if p['en'] and p['en'] != p['title'] else '',
                ' · '.join('`%s`' % E(x) for x in p['stack'][:4]) or '—',
                '<br><sub dir="auto">%s</sub>' % E(desc) if desc else ''))
        w('\n</details>\n')

    w('\n---\n\n## 🖼️ The site\n')
    w('\n<p align="center">\n<a href="%s"><img src="docs/site.webp" width="72%%" alt="Desktop"></a>'
      '\n<a href="%s"><img src="docs/site-mobile.webp" width="24%%" alt="Mobile"></a>\n</p>\n'
      % (live_url, live_url))
    w('\n**Picture labels** — every image on the site says what it is:\n')
    for k in ('live', 'template', 'repo', 'mockup', 'cover'):
        w('- **%s** (%s)' % (KIND_EN[k].capitalize(), KIND_LABEL[k]))
    w(TOOL_SECTION)
    return '\n'.join(out) + '\n'


TOOL_SECTION = '''

---

## ⚙️ How it is made — `showcase/`

A Python tool that turns a list of GitHub repos into this portfolio:

```text
clone ─► shoot ─► build ─► deploy        (+ readme → this file)
```

| Step | What happens |
|---|---|
| **clone** | Pulls every repo in `showcase/config.json` |
| **shoot** | Detects each project type and **runs it** — Django (migrates, creates a demo user and logs in), Flask, FastAPI, Streamlit, React/Vite/Next, static sites, Chrome extensions — then crawls it with headless Chromium for desktop + mobile screenshots |
| ↳ fallback | Renders the app's own HTML templates → pulls README / notebook images → draws a mock-up **from the source code** (Flutter `Text()` strings, icons and colours; Tkinter/Qt/WinForms labels; Arduino `Serial` output) → generated cover art |
| **build** | Static site: RTL Arabic, filters, search, galleries, favicon, dark mode |
| **deploy** | Uploads to PythonAnywhere, sets WSGI + static mappings, reloads |
| **admin** | `/admin` on the live site: upload screenshots to any project, create new projects, edit or hide — saved outside the deploy folder so redeploys never wipe it |

```bash
pip install playwright pillow jinja2 flask
python -m playwright install chromium

export PA_TOKEN=...            # PythonAnywhere API token — never commit it
python -m showcase all          # clone + shoot + build + deploy
python -m showcase shoot Injaz  # redo one project
python -m showcase readme --dest .   # regenerate this README
```

Details (Arabic): [`showcase/README.md`](showcase/README.md)
'''
