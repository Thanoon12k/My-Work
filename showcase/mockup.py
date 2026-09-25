"""Approximate screenshots for projects that cannot run in a browser.
Everything shown is pulled from the project's own source: Flutter Text() strings and
icons, Tkinter/Qt/WinForms labels, JSX text, the main code file, Serial output..."""
import html, os, re

from .detect import SKIP_DIRS, read

ESC = html.escape
AR = re.compile(r'[؀-ۿ]')
PALETTE = ['#4361EE', '#12B99C', '#FF5C39', '#9B7EDE', '#FFC93C', '#0EA5E9', '#E11D74']
FLUTTER_COLORS = {
    'blue': '#2196F3', 'indigo': '#3F51B5', 'teal': '#009688', 'green': '#4CAF50',
    'red': '#F44336', 'orange': '#FF9800', 'deepOrange': '#FF5722', 'purple': '#9C27B0',
    'deepPurple': '#673AB7', 'pink': '#E91E63', 'amber': '#FFC107', 'cyan': '#00BCD4',
    'lightBlue': '#03A9F4', 'blueGrey': '#607D8B', 'brown': '#795548', 'lime': '#CDDC39',
    'lightGreen': '#8BC34A', 'yellow': '#FFEB3B', 'grey': '#9E9E9E', 'black': '#222222',
}


def pick_color(slug):
    return PALETTE[sum(map(ord, slug)) % len(PALETTE)]


def files(root, exts, skip=()):
    for d, dirs, fs in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith('.')
                   and x not in skip and not os.path.exists(os.path.join(d, x, '.git'))]
        for f in fs:
            if f.lower().endswith(exts):
                yield os.path.join(d, f)


def uniq(items, n):
    out = []
    for i in items:
        i = re.sub(r'\s+', ' ', i).strip()
        if i and i not in out and not re.fullmatch(r'[\W\d_]+', i):
            out.append(i)
        if len(out) >= n:
            break
    return out


def is_rtl(texts):
    t = ' '.join(texts)
    return len(AR.findall(t)) > len(re.findall(r'[A-Za-z]', t)) * 0.5


FONT_URLS = ['https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=block',
             'https://fonts.googleapis.com/icon?family=Material+Icons+Round&display=block']
_FONT_CSS = None


def font_css():
    """Google Fonts inlined as data: URIs (cached on disk) so every render has them."""
    global _FONT_CSS
    if _FONT_CSS is not None:
        return _FONT_CSS
    import base64, hashlib, urllib.request
    cache = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out', '.fontcache')
    os.makedirs(cache, exist_ok=True)
    ua = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'}

    def get(url):
        p = os.path.join(cache, hashlib.md5(url.encode()).hexdigest())
        if not os.path.exists(p):
            data = urllib.request.urlopen(urllib.request.Request(url, headers=ua),
                                          timeout=30).read()
            open(p, 'wb').write(data)
        return open(p, 'rb').read()

    try:
        parts = []
        for u in FONT_URLS:
            css = get(u).decode('utf-8')
            css = re.sub(r'url\((https://[^)]+)\)', lambda m: 'url(data:font/woff2;base64,%s)'
                         % base64.b64encode(get(m.group(1))).decode(), css)
            parts.append(css)
        _FONT_CSS = '<style>%s</style>' % '\n'.join(parts)
    except Exception:
        _FONT_CSS = ''.join('<link href="%s" rel="stylesheet">' % u for u in FONT_URLS)
    return _FONT_CSS


def page(body, css='', w=1280, h=800, bg='#FFF6EA'):
    return '''<!doctype html><html><head><meta charset="utf-8">%s
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:%dpx;height:%dpx;overflow:hidden}
body{background:%s;font-family:Cairo,'Segoe UI',Tahoma,sans-serif;color:#16130D;
 display:flex;align-items:center;justify-content:center;position:relative}
.mi{font-family:'Material Icons Round';font-style:normal;font-size:22px;line-height:1;
 display:inline-block;direction:ltr;font-feature-settings:'liga';overflow:hidden;
 white-space:nowrap;max-width:1.2em}
.dots{position:absolute;inset:0;background-image:radial-gradient(#16130D18 1.5px,transparent 1.5px);
 background-size:22px 22px}
%s</style></head><body><div class="dots"></div>%s</body></html>''' % (
        font_css(), w, h, bg, css, body)


# ---------------------------------------------------------------- Flutter phones

def dart_str(s):
    s = re.sub(r'\$\{[^}]*\}|\$\w+', '', s)
    return s.replace("\\'", "'").replace('\\n', ' ').strip()


def flutter_screens(root, n=3):
    lib = os.path.join(root, 'lib')
    if not os.path.isdir(lib):
        for d, dirs, fs in os.walk(root):
            if 'pubspec.yaml' in fs and os.path.isdir(os.path.join(d, 'lib')):
                lib = os.path.join(d, 'lib')
                break
    color, app_title = None, None
    screens = []
    for p in files(lib, ('.dart',)):
        src = read(p)
        if not color:
            m = re.search(r'(?:seedColor|primaryColor|primarySwatch|primary)\s*:\s*'
                          r'(?:const\s+)?(?:Color\(0x[fF]{2}([0-9a-fA-F]{6})\)|Colors\.(\w+))', src)
            if m:
                color = '#' + m.group(1) if m.group(1) else FLUTTER_COLORS.get(m.group(2))
                rgb = color and [int(color[k:k + 2], 16) for k in (1, 3, 5)]
                if rgb and (sum(rgb) > 600 or max(rgb) - min(rgb) < 30):   # pale or grey
                    color = None          # too pale to be a brand colour
        m = re.search(r'MaterialApp(?:\.router)?\([^;]*?title:\s*[\'"]([^\'"]+)', src, re.S)
        if m and not app_title:
            app_title = m.group(1)
        if 'Scaffold(' not in src and 'build(' not in src:
            continue
        texts = [dart_str(t) for t in re.findall(
            r'Text\(\s*(?:const\s+)?[\'"]((?:[^\'"\\]|\\.){2,60})[\'"]', src)]
        fields = [dart_str(t) for t in re.findall(
            r'(?:labelText|hintText)\s*:\s*[\'"]((?:[^\'"\\]|\\.){2,40})[\'"]', src)]
        icons = [re.sub(r'_(rounded|outlined|sharp)$', '', i)
                 for i in re.findall(r'Icons\.([a-z0-9_]+)', src)]
        title = re.search(r'AppBar\((?:[^;]{0,300}?)title:\s*(?:const\s+)?Text\(\s*[\'"]'
                          r'((?:[^\'"\\]|\\.){2,40})[\'"]', src, re.S)
        nav = re.findall(r'BottomNavigationBarItem\([^)]*?icon:\s*(?:const\s+)?Icon\(\s*Icons\.'
                         r'(\w+)\)[^)]*?label:\s*[\'"]([^\'"]+)', src, re.S)
        nav += [(i, l) for i, l in re.findall(
            r'NavigationDestination\([^)]*?icon:\s*(?:const\s+)?Icon\(\s*Icons\.(\w+)\)[^)]*?'
            r'label:\s*[\'"]([^\'"]+)', src, re.S)]
        texts = uniq(texts, 14)
        score = len(texts) + 2 * len(fields) + (5 if title else 0) + (3 if nav else 0)
        if score < 4:
            continue
        screens.append({'score': score, 'file': os.path.basename(p),
                        'title': dart_str(title.group(1)) if title else '',
                        'texts': texts, 'fields': uniq(fields, 4), 'icons': uniq(icons, 12),
                        'nav': nav[:5], 'fab': 'FloatingActionButton' in src})
    screens.sort(key=lambda s: -s['score'])
    # prefer screens whose file name says "home"/"dashboard" first
    screens.sort(key=lambda s: 0 if re.search(r'home|dashboard|main', s['file']) else 1)
    return screens[:n], color, app_title


def phone_html(s, color, rtl):
    icons = s['icons'] or ['circle']
    texts = list(s['texts'])
    title = s['title'] or (texts.pop(0) if texts else '')
    buttons = [t for t in texts if len(t) <= 12][-2:]
    body_texts = [t for t in texts if t not in buttons]
    head = body_texts[:1]
    rows = body_texts[1:7]
    parts = []
    if head:
        parts.append('<div class="hero" style="background:%s">%s<b>%s</b></div>'
                     % (color, '<i class="mi">%s</i>' % icons[0], ESC(head[0])))
    for f in s['fields']:
        parts.append('<div class="field"><span>%s</span></div>' % ESC(f))
    for i, t in enumerate(rows):
        ic = icons[(i + 1) % len(icons)]
        parts.append('<div class="tile"><i class="mi" style="color:%s;background:%s1f">%s</i>'
                     '<div><b>%s</b><small></small></div></div>' % (color, color, ic, ESC(t)))
    if buttons:
        parts.append('<div class="btns">%s</div>' % ''.join(
            '<span style="%s">%s</span>' % (
                'background:%s;color:#fff' % color if k == 0 else 'border:2px solid %s;color:%s'
                % (color, color), ESC(b)) for k, b in enumerate(buttons)))
    nav = ''
    if s['nav']:
        nav = '<div class="nav">%s</div>' % ''.join(
            '<div style="%s"><i class="mi">%s</i><small>%s</small></div>'
            % ('color:%s' % color if k == 0 else '', ic, ESC(l)) for k, (ic, l) in
            enumerate(s['nav']))
    fab = '<div class="fab" style="background:%s"><i class="mi">add</i></div>' % color \
        if s['fab'] else ''
    return '''<div class="phone" dir="%s"><div class="scr">
<div class="status"><span>9:41</span><span><i class="mi">signal_cellular_alt</i><i class="mi">wifi</i><i class="mi">battery_full</i></span></div>
<div class="bar" style="background:%s"><i class="mi">menu</i><b>%s</b><i class="mi">notifications_none</i></div>
<div class="content">%s</div>%s%s</div></div>''' % (
        'rtl' if rtl else 'ltr', color, ESC(title), ''.join(parts), fab, nav)


PHONE_CSS = '''
.stage{position:relative;display:flex;gap:46px;align-items:center}
.phone{width:300px;height:620px;border:3px solid #16130D;border-radius:44px;background:#16130D;
 padding:10px;box-shadow:-10px 10px 0 #16130D}
.phone:nth-child(2){transform:translateY(-26px)}
.scr{width:100%;height:100%;border-radius:34px;overflow:hidden;background:#F6F7FB;position:relative;
 display:flex;flex-direction:column}
.status{display:flex;justify-content:space-between;padding:8px 22px 4px;font-size:12px;font-weight:700;
 background:#fff}.status .mi{font-size:14px}
.bar{display:flex;align-items:center;gap:10px;padding:12px 16px;color:#fff}
.bar b{flex:1;font-size:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.content{flex:1;padding:12px;display:flex;flex-direction:column;gap:9px;overflow:hidden}
.hero{border-radius:18px;color:#fff;padding:16px;display:flex;flex-direction:column;gap:6px;min-height:92px}
.hero b{font-size:17px;line-height:1.35}.hero .mi{font-size:30px;opacity:.9}
.tile{display:flex;align-items:center;gap:10px;background:#fff;border-radius:14px;padding:9px 11px;
 box-shadow:0 1px 3px #0001}
.tile .mi{width:36px;height:36px;border-radius:11px;display:flex;align-items:center;justify-content:center;font-size:20px}
.tile b{font-size:13px;font-weight:600;display:block;line-height:1.4}
.tile small{display:block;height:6px;width:70px;background:#E5E7EB;border-radius:4px;margin-top:4px}
.field{background:#fff;border:1.5px solid #D1D5DB;border-radius:12px;padding:10px 12px;font-size:12px;color:#6B7280}
.btns{display:flex;gap:8px;margin-top:auto}.btns span{flex:1;text-align:center;border-radius:12px;
 padding:9px;font-size:13px;font-weight:700}
.nav{display:flex;justify-content:space-around;background:#fff;padding:8px 4px 12px;border-top:1px solid #eee}
.nav div{display:flex;flex-direction:column;align-items:center;font-size:10px;color:#9CA3AF}
.fab{position:absolute;bottom:70px;inset-inline-end:18px;width:52px;height:52px;border-radius:16px;
 color:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 10px #0003}
'''


def flutter_mock(project, root):
    screens, color, app_title = flutter_screens(root)
    if not screens:
        return None
    color = color or pick_color(project['slug'])
    rtl = is_rtl(sum((s['texts'] for s in screens), []))
    body = '<div class="stage">%s</div>' % ''.join(phone_html(s, color, rtl) for s in screens)
    return page(body, PHONE_CSS, bg='#FFF6EA')


# ---------------------------------------------------------------- desktop windows

def gui_widgets(root, kind):
    title, buttons, labels, fields, headers = None, [], [], 0, []
    exts = {'pygui': ('.py',), 'dotnet': ('.vb', '.cs'), 'electron': ('.jsx', '.tsx', '.js'),
            'cra': ('.jsx', '.tsx', '.js'), 'vite': ('.jsx', '.tsx', '.vue'),
            'next': ('.jsx', '.tsx'), 'node': ('.jsx', '.tsx', '.js')}.get(kind, ('.py',))
    for p in files(root, exts, skip=('build', 'dist', 'public')):
        if p.endswith('.js') and ('.min.' in p or os.path.getsize(p) > 150_000):
            continue
        src = read(p)
        if kind == 'pygui':
            m = re.search(r'\.(?:title|setWindowTitle)\(\s*[fr]?[\'"]([^\'"]{2,60})', src)
            title = title or (m and m.group(1))
            buttons += re.findall(r'Button\([^)]*?text\s*=\s*[fr]?[\'"]([^\'"{]{1,30})', src)
            buttons += re.findall(r'QPushButton\(\s*[fr]?[\'"]([^\'"{]{1,30})', src)
            labels += re.findall(r'Label\([^)]*?text\s*=\s*[fr]?[\'"]([^\'"{]{2,50})', src)
            labels += re.findall(r'QLabel\(\s*[fr]?[\'"]([^\'"{]{2,50})', src)
            labels += re.findall(r'setText\(\s*[fr]?[\'"]([^\'"{]{2,50})', src)
            fields += len(re.findall(r'\b(?:CTk)?Entry\(|QLineEdit\(|QComboBox\(|Combobox\(', src))
            headers += re.findall(r'\.heading\([^,]+,\s*text\s*=\s*[\'"]([^\'"]+)', src)
            for m in re.findall(r'setHorizontalHeaderLabels\(\s*\[([^\]]+)\]', src):
                headers += re.findall(r'[\'"]([^\'"]+)[\'"]', m)
        elif kind == 'dotnet':
            m = re.search(r'Me\.Text\s*=\s*"([^"]+)"', src)
            title = title or (m and m.group(1))
            for ctl, txt in re.findall(r'Me\.(\w+)\.Text\s*=\s*"([^"]{1,50})"', src):
                (buttons if 'button' in ctl.lower() else labels).append(txt)
            fields += len(re.findall(r'New System\.Windows\.Forms\.(?:TextBox|ComboBox|'
                                     r'DateTimePicker)\b', src))
            headers += re.findall(r'HeaderText\s*=\s*"([^"]+)"', src)
        else:
            for t in re.findall(r'>\s*([^<>{}\n]{3,40}?)\s*<', src):
                if not re.search(r'[=;()]|&&|\|\|', t):
                    labels.append(t)
            buttons += re.findall(r'<button[^>]*>\s*([^<>{}\n]{2,24})\s*<', src, re.I)
            fields += len(re.findall(r'<input\b|<select\b|<textarea\b', src, re.I))
            m = re.search(r'<title>([^<]+)</title>', src)
            title = title or (m and m.group(1))
    return {'title': title, 'buttons': uniq(buttons, 7), 'labels': uniq(labels, 12),
            'fields': min(fields, 5), 'headers': uniq(headers, 5)}


DESK_CSS = '''
.win{position:relative;width:1080px;height:640px;background:#fff;border:3px solid #16130D;border-radius:18px;
 box-shadow:-12px 12px 0 #16130D;overflow:hidden;display:flex;flex-direction:column}
.tb{height:44px;background:#16130D;color:#fff;display:flex;align-items:center;gap:8px;padding:0 16px;font-size:14px}
.tb i{width:12px;height:12px;border-radius:50%;display:inline-block}
.tb b{flex:1;text-align:center;font-weight:600}
.main{flex:1;display:flex;min-height:0}
.side{width:230px;padding:18px 14px;display:flex;flex-direction:column;gap:8px;color:#fff}
.side .it{padding:10px 12px;border-radius:12px;font-size:14px;font-weight:600;display:flex;gap:10px;
 align-items:center;background:#ffffff18}
.side .it:first-child{background:#ffffff40}
.body{flex:1;padding:22px 26px;display:flex;flex-direction:column;gap:14px;background:#F8FAFC;min-width:0}
.body h2{font-size:22px;font-weight:800}
.kpis{display:flex;gap:12px}.kpi{flex:1;background:#fff;border:1.5px solid #E5E7EB;border-radius:14px;padding:12px 14px}
.kpi small{font-size:12px;color:#6B7280;display:block}.kpi b{font-size:22px}
.form{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.form div{background:#fff;border:1.5px solid #D1D5DB;border-radius:10px;padding:9px 12px;font-size:13px;color:#6B7280}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;font-size:13px}
th{text-align:start;padding:9px 12px;color:#fff}td{padding:9px 12px;border-top:1px solid #EEF0F4}
td span{display:inline-block;height:8px;border-radius:4px;background:#E5E7EB}
.acts{display:flex;gap:10px;flex-wrap:wrap}.acts span{padding:9px 18px;border-radius:10px;font-size:13px;font-weight:700}
'''


def desktop_mock(project, root, kind):
    w = gui_widgets(root, kind)
    if len(w['buttons']) + len(w['labels']) < 3:
        return None
    color = pick_color(project['slug'])
    rtl = is_rtl(w['buttons'] + w['labels'])
    side_items = (w['buttons'] or w['labels'])[:6]
    icons = ['dashboard', 'folder_open', 'add_circle', 'search', 'bar_chart', 'settings']
    side = ''.join('<div class="it"><i class="mi">%s</i>%s</div>' % (icons[i % 6], ESC(t))
                   for i, t in enumerate(side_items))
    labels = [l for l in w['labels'] if l not in side_items]
    heading = labels.pop(0) if labels else (w['title'] or project['title'])
    kpis = ''.join('<div class="kpi"><small>%s</small><b>%s</b></div>' % (ESC(l), v)
                   for l, v in zip(labels[:3], ('128', '24', '96%')))
    form = ''
    if w['fields']:
        form = '<div class="form">%s</div>' % ''.join(
            '<div>%s</div>' % ESC(l) for l in (labels[3:3 + w['fields']] or
                                               ['...'] * min(w['fields'], 4)))
    heads = w['headers'] or labels[3:7] or ['#', 'Name', 'Date', 'Status']
    rows = ''.join('<tr>%s</tr>' % ''.join('<td><span style="width:%dpx"></span></td>'
                                           % (40 + (r * 37 + c * 23) % 70)
                                           for c in range(len(heads))) for r in range(5))
    table = '<table><tr>%s</tr>%s</table>' % (
        ''.join('<th style="background:%s">%s</th>' % (color, ESC(h)) for h in heads), rows)
    acts = ''.join('<span style="%s">%s</span>' % (
        'background:%s;color:#fff' % color if i == 0 else 'border:2px solid %s;color:%s'
        % (color, color), ESC(b)) for i, b in enumerate(w['buttons'][6:9] or w['buttons'][:2]))
    body = '''<div class="win" dir="%s"><div class="tb" dir="ltr"><i style="background:#FF5F57"></i>
<i style="background:#FEBC2E"></i><i style="background:#28C840"></i><b>%s</b></div>
<div class="main"><div class="side" style="background:%s">%s</div>
<div class="body"><h2>%s</h2><div class="kpis">%s</div>%s%s<div class="acts">%s</div></div></div></div>''' % (
        'rtl' if rtl else 'ltr', ESC(w['title'] or project['title']), color, side, ESC(heading),
        kpis, form, table, acts)
    return page(body, DESK_CSS)


# ---------------------------------------------------------------- code + output

KW = {'py': r'\b(def|class|import|from|return|if|elif|else|for|while|in|try|except|with|as|'
            r'lambda|None|True|False|and|or|not|self|async|await|yield)\b',
      'c': r'\b(void|int|float|double|char|bool|if|else|for|while|return|const|#include|'
           r'#define|class|public|private|struct|unsigned|long|byte|String|true|false|new|'
           r'delay|pinMode|digitalWrite|analogRead|Serial|module|simple|network|parameters|'
           r'gates|submodules|connections|import|package)\b',
      'js': r'\b(const|let|var|function|return|if|else|for|while|import|from|export|default|'
            r'class|new|async|await|true|false|null)\b'}


def highlight(code, lang):
    comment = r'//[^\n]*' if lang in ('c', 'js') else r'#[^\n]*'
    if lang == 'c':
        comment = r'//[^\n]*|/\*.*?\*/'
    tok = re.compile(r'(?P<cm>%s)|(?P<st>"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\')|'
                     r'(?P<kw>%s)|(?P<nu>\b\d+(?:\.\d+)?\b)' % (comment, KW.get(lang, KW['py'])),
                     re.S)
    out, pos = [], 0
    for m in tok.finditer(code):
        out.append(ESC(code[pos:m.start()]))
        out.append('<span class="%s">%s</span>' % (m.lastgroup, ESC(m.group(0))))
        pos = m.end()
    out.append(ESC(code[pos:]))
    return ''.join(out)


def code_excerpt(path, lines=24):
    src = read(path, 400_000)
    if path.endswith('.ipynb'):
        import json
        try:
            nb = json.loads(src)
            src = '\n\n'.join(''.join(c['source']) for c in nb.get('cells', [])
                              if c.get('cell_type') == 'code')
        except (ValueError, KeyError):
            pass
    ls = src.replace('\t', '    ').split('\n')
    # skip the import/include wall at the top
    i = 0
    while i < len(ls) and (not ls[i].strip() or re.match(
            r'\s*(import |from |#include|using |package |//|#!|# -\*-|"""|\'\'\')', ls[i])):
        i += 1
    i = max(0, i - 2) if i < len(ls) - 8 else 0
    chunk = []
    for l in ls[i:]:
        if not l.strip() and chunk and not chunk[-1].strip():
            continue                      # collapse blank runs
        chunk.append(l[:92])
        if len(chunk) >= lines:
            break
    return '\n'.join(chunk).rstrip()


def outputs(root, kind):
    """Strings the program prints — shown in a terminal/serial pane."""
    pats = {'arduino': r'Serial\d?\.print(?:ln)?\(\s*"([^"]{2,60})"',
            'python': r'print\(\s*f?[\'"]([^\'"{]{3,60})',
            'notebook': r'print\(\s*f?[\'"]([^\'"{]{3,60})',
            'omnet': r'EV\s*<<\s*"([^"]{3,60})"',
            'java': r'System\.out\.println\(\s*"([^"]{3,60})"',
            'js': r'console\.log\(\s*[\'"`]([^\'"`$]{3,60})'}
    exts = {'arduino': ('.ino', '.cpp', '.h'), 'python': ('.py',), 'notebook': ('.ipynb',),
            'omnet': ('.cc',), 'java': ('.java',), 'js': ('.js',)}
    if kind not in pats:
        return []
    found = []
    for p in files(root, exts[kind]):
        found += re.findall(pats[kind], read(p))
        if len(found) > 40:
            break
    return uniq(found, 9)


CODE_CSS = '''
.wrap{position:relative;display:flex;gap:26px;align-items:stretch;width:1180px;height:680px}
.ed{flex:1.35;background:#1E1E2E;border:3px solid #16130D;border-radius:18px;box-shadow:-12px 12px 0 #16130D;
 overflow:hidden;display:flex;flex-direction:column;min-width:0}
.tabs{display:flex;align-items:center;gap:8px;background:#16130D;padding:10px 14px;color:#ccc;font-size:13px}
.tabs i{width:11px;height:11px;border-radius:50%;display:inline-block}
.tabs b{margin-inline-start:12px;background:#1E1E2E;color:#fff;padding:5px 14px;border-radius:8px 8px 0 0;font-weight:600}
pre{flex:1;margin:0;padding:16px 18px;font:14px/1.62 'JetBrains Mono',Consolas,monospace;color:#E4E4EF;
 overflow:hidden;counter-reset:l}
.kw{color:#C792EA}.st{color:#C3E88D}.cm{color:#6A7394;font-style:italic}.nu{color:#F78C6C}
.col{flex:1;display:flex;flex-direction:column;gap:20px;min-width:0}
.card{background:#fff;border:3px solid #16130D;border-radius:18px;box-shadow:-8px 8px 0 #16130D;padding:20px 22px}
.card h1{font-size:26px;line-height:1.3;font-weight:900;margin-bottom:8px}
.card p{font-size:14px;line-height:1.7;color:#5C554A}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}.tags span{border:2px solid #16130D;border-radius:30px;
 padding:2px 12px;font-size:12px;font-weight:700}
.term{flex:1;background:#0B0F14;border:3px solid #16130D;border-radius:18px;box-shadow:-8px 8px 0 #16130D;
 padding:14px 18px;font:13px/1.7 Consolas,monospace;color:#9EF01A;overflow:hidden}
.term div::before{content:'› ';color:#555}.term h4{color:#888;font:600 12px Cairo;margin-bottom:6px}
'''


def main_code_file(project, root):
    kind = project['primary']
    where = project['where'].get(kind, '')
    p = os.path.join(root, where)
    if os.path.isfile(p):
        return p
    exts = {'omnet': ('.ned', '.cc'), 'java': ('.java',), 'dotnet': ('.vb', '.cs'),
            'arduino': ('.ino',), 'js': ('.js',)}.get(kind, ('.py', '.js', '.dart', '.java'))
    best = None
    for f in files(p if os.path.isdir(p) else root, exts):
        size = os.path.getsize(f)
        if 800 < size < 200_000 and (best is None or size > best[0]):
            best = (size, f)
    return best and best[1]


def code_mock(project, root):
    kind = project['primary']
    f = main_code_file(project, root)
    if not f:
        return None
    code = code_excerpt(f)
    if not code.strip():
        return None
    lang = 'c' if f.endswith(('.ino', '.cc', '.h', '.cpp', '.ned', '.java', '.cs')) else \
        'js' if f.endswith(('.js', '.ts', '.jsx')) else 'py'
    out_kind = {'pygui': 'python', 'gradio': 'python'}.get(kind, kind)
    outs = outputs(root, out_kind)
    term = ''
    if outs:
        label = 'Serial Monitor · 9600 baud' if kind == 'arduino' else 'Output'
        term = '<div class="term" dir="auto"><h4>%s</h4>%s</div>' % (
            label, ''.join('<div>%s</div>' % ESC(o) for o in outs))
    desc = project.get('description_ar') or project.get('description') or ''
    bullets = project.get('bullets') or []
    if not desc and bullets:
        desc = ' · '.join(bullets[:3])
    tags = ''.join('<span>%s</span>' % ESC(t) for t in project.get('stack', [])[:6])
    card = '<div class="card" dir="auto"><h1>%s</h1><p>%s</p><div class="tags">%s</div></div>' % (
        ESC(project.get('title_ar') or project['title']), ESC(desc[:260]), tags)
    body = '''<div class="wrap"><div class="ed"><div class="tabs"><i style="background:#FF5F57"></i>
<i style="background:#FEBC2E"></i><i style="background:#28C840"></i><b>%s</b></div>
<pre>%s</pre></div><div class="col">%s%s</div></div>''' % (
        ESC(os.path.basename(f)), highlight(code, lang), card, term)
    return page(body, CODE_CSS)


# ---------------------------------------------------------------- entry point

def make(project, root):
    """Return a list of (name, html, caption) mockups for this project."""
    kind = project['primary']
    out = []
    if 'flutter' in project['kinds']:
        h = flutter_mock(project, root)
        if h:
            out.append(('mock-app', h, 'App screens (from source)'))
    if kind in ('pygui', 'dotnet', 'electron', 'cra', 'vite', 'next', 'node'):
        h = desktop_mock(project, root, kind)
        if h:
            out.append(('mock-ui', h, 'Interface (from source)'))
    if not out or kind in ('arduino', 'omnet', 'java', 'python', 'notebook', 'js'):
        h = code_mock(project, root)
        if h:
            out.append(('mock-code', h, 'Source'))
    out.append(('cover', cover_mock(project), 'Cover'))
    return out


# ---------------------------------------------------------------- generated cover art

TOPICS = [  # (keyword regex, material icon, second icon, colour)
    (r'clinic|medic|pharm|doctor|patient|hospital|syringe|عياد|دواء|طبي', 'medical_services',
     'vaccines', '#12B99C'),
    (r'generator|مولد|ampere', 'electric_bolt', 'receipt_long', '#FF5C39'),
    (r'tour|travel|سياح', 'travel_explore', 'photo_camera', '#4361EE'),
    (r'ocr|handwrit|scan|bubble', 'document_scanner', 'text_fields', '#4361EE'),
    (r'audio|voice|speech|mp3|speak|sound', 'graphic_eq', 'mic', '#9B7EDE'),
    (r'video|youtube|studio', 'movie', 'subtitles', '#FF5C39'),
    (r'chess', 'extension', 'psychology', '#16130D'),
    (r'cloud|fog|network|router|aqm|simulat', 'hub', 'lan', '#0EA5E9'),
    (r'agent|\bai\b|lstm|neural|optimi|mrfo|ga\b|gpt|llm', 'psychology', 'auto_awesome', '#12B99C'),
    (r'finger|zk|attendance', 'fingerprint', 'badge', '#4361EE'),
    (r'temp|sensor|esp|iot|arduino|oscillo|hand', 'sensors', 'memory', '#FF5C39'),
    (r'pdf|word|excel|thesis|note|doc', 'description', 'edit_note', '#FFC93C'),
    (r'captcha|tik|proxy', 'verified_user', 'vpn_lock', '#E11D74'),
    (r'wallpaper|background|image|photo', 'wallpaper', 'image', '#12B99C'),
    (r'chat|message', 'forum', 'send', '#4361EE'),
    (r'employee|customer|manager|project|clinic|invoice', 'groups', 'insights', '#12B99C'),
    (r'cat|fact|api', 'api', 'data_object', '#9B7EDE'),
]

COVER_CSS = '''
.cv{position:relative;width:1120px;height:640px;border:3px solid #16130D;border-radius:28px;
 box-shadow:-14px 14px 0 #16130D;overflow:hidden;display:flex;align-items:center;padding:0 70px;gap:60px}
.art{position:relative;width:360px;height:360px;flex:none}
.blob{position:absolute;inset:0;border-radius:42% 58% 55% 45%/48% 42% 58% 52%;border:3px solid #16130D;
 box-shadow:-10px 10px 0 #16130D;background:#fff;display:flex;align-items:center;justify-content:center}
.blob .mi{font-size:190px}
.chip2{position:absolute;right:-20px;bottom:10px;width:120px;height:120px;border-radius:30px;border:3px solid #16130D;
 background:#FFC93C;display:flex;align-items:center;justify-content:center;box-shadow:-6px 6px 0 #16130D;transform:rotate(8deg)}
.chip2 .mi{font-size:68px}
.ring{position:absolute;border:3px dashed #16130D55;border-radius:50%}
.txt{flex:1;min-width:0}
.txt small{display:inline-block;background:#fff;border:3px solid #16130D;border-radius:40px;padding:4px 18px;
 font-weight:800;font-size:16px;margin-bottom:18px}
.txt h1{font-size:54px;line-height:1.15;font-weight:900;color:#16130D;margin-bottom:16px;word-break:break-word}
.txt p{font-size:19px;line-height:1.7;color:#16130DCC}
.lines{position:absolute;inset:0;background:repeating-linear-gradient(135deg,#ffffff22 0 2px,transparent 2px 26px)}
'''


def cover_mock(project):
    text = ' '.join([project['slug'], project['title'], project.get('description', '')]).lower()
    icon, icon2, color = 'code', 'terminal', pick_color(project['slug'])
    for rx, i1, i2, c in TOPICS:
        if re.search(rx, text):
            icon, icon2, color = i1, i2, c
            break
    title = project.get('title_ar') or project['title']
    desc = project.get('description_ar') or project.get('description') or \
        ' · '.join(project.get('bullets', [])[:3])
    label = ' · '.join(project.get('stack', [])[:3]) or 'Project'
    fg = '#16130D' if color in ('#FFC93C',) else '#fff'
    body = '''<div class="cv" style="background:%s" dir="auto"><div class="lines"></div>
<div class="art"><div class="ring" style="inset:-40px"></div><div class="ring" style="inset:-80px"></div>
<div class="blob"><i class="mi" style="color:%s">%s</i></div><div class="chip2"><i class="mi">%s</i></div></div>
<div class="txt"><small>%s</small><h1 style="color:%s">%s</h1><p style="color:%s">%s</p></div></div>''' % (
        color, color if color != '#FFC93C' else '#16130D', icon, icon2, ESC(label), fg,
        ESC(title), fg, ESC(desc[:200]))
    return page(body, COVER_CSS)
