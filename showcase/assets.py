"""Pictures a repo already has: README screenshots, screenshot folders, notebook plots."""
import base64, io, json, os, re, urllib.request

from .detect import SKIP_DIRS, read

IMG_EXT = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
GOOD_NAME = re.compile(r'screen|shot|capture|preview|demo|ui|mockup|image\d|photo|صورة', re.I)
BAD_NAME = re.compile(r'icon|logo|favicon|launch|splash|avatar|background|bg[_-]|sprite|'
                      r'placeholder|arrow|button|flag|emoji|badge|shield', re.I)
MIN_W, MIN_H = 320, 240


def image_ok(blob):
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(blob))
        w, h = im.size
        if w < MIN_W or h < MIN_H or w / h > 5 or h / w > 5:
            return None
        return im
    except Exception:
        return None


def readme_refs(root, readme_rel):
    if not readme_rel:
        return []
    text = read(os.path.join(root, readme_rel))
    refs = re.findall(r'!\[[^\]]*\]\(\s*<?([^)\s>]+)', text)
    refs += re.findall(r'<img[^>]+src=["\']([^"\']+)', text, re.I)
    return refs


def fetch(url, limit=8_000_000):
    url = re.sub(r'github\.com/([^/]+)/([^/]+)/blob/', r'github.com/\1/\2/raw/', url)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'showcase/1.0'})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read(limit)
    except Exception:
        return None


def collect(project, root, outdir, max_images=6, remote=True):
    shots, seen = [], set()

    def add(blob, caption):
        if len(shots) >= max_images or not blob:
            return
        key = hash(blob[:4096]) ^ len(blob)
        if key in seen:
            return
        im = image_ok(blob)
        if im is None:
            return
        seen.add(key)
        name = 'repo%02d.png' % (len(shots) + 1)
        im = im.convert('RGBA') if im.mode in ('P', 'LA') else im
        if getattr(im, 'is_animated', False):
            im.seek(0)
        im.convert('RGB').save(os.path.join(outdir, name))
        w, h = im.size
        shots.append({'file': name, 'kind': 'repo', 'caption': caption,
                      'device': 'mobile' if h > w * 1.3 else 'desktop'})

    # 1. images the README shows
    for ref in readme_refs(root, project.get('readme')):
        if re.search(r'shields\.io|badge|travis|codecov|img\.icons8|skillicons', ref, re.I):
            continue
        if ref.startswith(('http://', 'https://')):
            if remote:
                add(fetch(ref), 'README')
        else:
            p = os.path.normpath(os.path.join(root, os.path.dirname(project['readme']),
                                              ref.split('?')[0]))
            if os.path.isfile(p) and not BAD_NAME.search(os.path.basename(p)):
                add(open(p, 'rb').read(), os.path.splitext(os.path.basename(p))[0])

    # 2. image files that look like screenshots
    cands = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith('.')
                   and x not in ('android', 'ios', 'windows', 'macos', 'linux', 'static',
                                 'public', 'node_modules', 'res', 'mipmap')]
        for fn in files:
            if fn.lower().endswith(IMG_EXT) and not BAD_NAME.search(fn):
                p = os.path.join(d, fn)
                in_shots_dir = GOOD_NAME.search(os.path.relpath(d, root))
                if GOOD_NAME.search(fn) or in_shots_dir:
                    cands.append((0 if in_shots_dir else 1, os.path.getsize(p), p))
    for _, _, p in sorted(cands, key=lambda c: (c[0], -c[1]))[:20]:
        add(open(p, 'rb').read(), os.path.splitext(os.path.basename(p))[0])

    # 3. plots saved inside notebooks
    if 'notebook' in project['kinds'] and len(shots) < max_images:
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith('.')]
            for fn in files:
                if not fn.endswith('.ipynb'):
                    continue
                try:
                    nb = json.loads(read(os.path.join(d, fn), 30_000_000))
                except ValueError:
                    continue
                for cell in nb.get('cells', []):
                    for o in cell.get('outputs', []):
                        png = (o.get('data') or {}).get('image/png')
                        if png:
                            if isinstance(png, list):
                                png = ''.join(png)
                            try:
                                add(base64.b64decode(png), fn[:-6] + ' output')
                            except Exception:
                                pass
    return shots
