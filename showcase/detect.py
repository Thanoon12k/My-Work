"""Work out what kind of project a folder is, and pull out what the portfolio needs
(title, description, stack, category, entry points)."""
import json, os, re

SKIP_DIRS = {'.git', 'node_modules', 'venv', '.venv', 'env', '__pycache__', 'build',
             'dist', '.dart_tool', '.idea', '.vscode', 'site-packages', '.next',
             'Pods', '.gradle', 'target', 'bin', 'obj', '.mvn', 'migrations'}
MAX_DEPTH = 4

# primary kind -> (portfolio category, human label)
KINDS = {
    'django':    ('web', 'Django'),
    'flask':     ('web', 'Flask'),
    'fastapi':   ('web', 'FastAPI'),
    'streamlit': ('web', 'Streamlit'),
    'gradio':    ('ai', 'Gradio'),
    'next':      ('web', 'Next.js'),
    'vite':      ('web', 'Vite'),
    'cra':       ('web', 'React'),
    'electron':  ('desktop', 'Electron'),
    'node':      ('web', 'Node.js'),
    'static':    ('web', 'HTML/CSS'),
    'extension': ('web', 'Browser extension'),
    'flutter':   ('mobile', 'Flutter'),
    'pygui':     ('desktop', 'Python desktop'),
    'notebook':  ('ai', 'Jupyter'),
    'arduino':   ('hw', 'Arduino'),
    'omnet':     ('sim', 'OMNeT++'),
    'java':      ('sim', 'Java'),
    'dotnet':    ('desktop', '.NET'),
    'python':    ('tools', 'Python'),
    'js':        ('tools', 'JavaScript'),
    'docs':      ('docs', 'Notes'),
}
# order = which one wins when a repo has several
PRIORITY = ['django', 'flask', 'fastapi', 'streamlit', 'gradio', 'next', 'vite', 'cra',
            'static', 'extension', 'flutter', 'electron', 'node', 'pygui', 'notebook',
            'arduino', 'omnet', 'java', 'dotnet', 'python', 'js', 'docs']
RUNNABLE = {'django', 'flask', 'fastapi', 'streamlit', 'gradio', 'next', 'vite', 'cra',
            'node', 'static', 'extension'}

AI_WORDS = re.compile(r'\b(tensorflow|keras|torch|sklearn|openai|anthropic|langchain|'
                      r'transformers|cv2|opencv|lstm|ocr|whisper|groq|gemini|rembg)\b', re.I)


def walk(root):
    root = os.path.abspath(root)
    base = root.count(os.sep)
    for d, dirs, files in os.walk(root):
        depth = d.count(os.sep) - base
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith('.')
                   and depth < MAX_DEPTH and not nested_repo(os.path.join(d, x))]
        yield d, files


def nested_repo(d):
    """A folder that is its own git repo (e.g. clones inside out/) belongs to another project."""
    return os.path.exists(os.path.join(d, '.git'))


def read(path, limit=200_000):
    try:
        with open(path, 'rb') as f:
            raw = f.read(limit)
    except OSError:
        return ''
    enc = 'utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig'
    return raw.decode(enc, errors='replace')


BOILERPLATE = re.compile(r'^(a new flutter project|getting started|this project was bootstrapped|'
                         r'project name|this project is aimed at|day \d|electron app design|'
                         r'"?# )', re.I)


def readme(root):
    for name in os.listdir(root):
        if name.lower().startswith('readme') and name.lower().endswith(('.md', '.txt', '')):
            p = os.path.join(root, name)
            if os.path.isfile(p):
                return p, read(p)
    return None, ''


def summarize_readme(text):
    """First heading + first real paragraph + bullet list."""
    title, para, bullets = None, [], []
    in_code = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('```'):
            in_code = not in_code
            continue
        if in_code or not s or s.startswith(('<', '![', '[![', '|', '---', '===')):
            if para and not s and len(' '.join(para)) > 60:
                break
            continue
        if s.startswith('#'):
            h = s.lstrip('#').strip()
            if not title and h:
                title = h
            elif para:
                break
            continue
        if re.match(r'^[-*+]\s+|^\d+\.\s+', s):
            b = re.sub(r'^[-*+]\s+|^\d+\.\s+', '', s)
            if len(bullets) < 6 and 3 < len(b) < 140:
                bullets.append(clean_md(b))
            continue
        if len(' '.join(para)) < 420:
            para.append(s)
    return title and clean_md(title), clean_md(' '.join(para))[:420], bullets


def clean_md(s):
    s = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', s)
    s = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', s)
    s = re.sub(r'[*_`]{1,3}', '', s)
    s = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def pretty_name(slug):
    s = re.sub(r'[_\-]+', ' ', slug).strip()
    s = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', s)
    return ' '.join(w if w.isupper() else w[:1].upper() + w[1:] for w in s.split())


def detect(root, slug=None):
    root = os.path.abspath(root)
    slug = slug or os.path.basename(root)
    found = {}          # kind -> path (dir or file) that proved it
    stack = set()
    py_files, ai_hits = [], 0

    def mark(kind, where):
        found.setdefault(kind, where)

    for d, files in walk(root):
        rel = os.path.relpath(d, root)
        parts = set(rel.replace('\\', '/').split('/'))
        fl = set(files)
        if 'manage.py' in fl:
            mark('django', d)
        if 'pubspec.yaml' in fl and 'flutter' in read(os.path.join(d, 'pubspec.yaml')):
            mark('flutter', d)
        if 'package.json' in fl:
            try:
                pj = json.loads(read(os.path.join(d, 'package.json')) or '{}')
            except ValueError:
                pj = {}
            deps = {**pj.get('dependencies', {}), **pj.get('devDependencies', {})}
            stack.update(v for k, v in (('react', 'React'), ('vue', 'Vue'),
                                        ('express', 'Express'), ('tailwindcss', 'Tailwind'),
                                        ('typescript', 'TypeScript'), ('redux', 'Redux'))
                         if k in deps)
            scripts = pj.get('scripts', {})
            if 'next' in deps:
                mark('next', d)
            elif 'electron' in deps:
                mark('electron', d)
            elif 'vite' in deps:
                mark('vite', d)
            elif 'react-scripts' in deps:
                mark('cra', d)
            elif scripts.get('start') or scripts.get('dev'):
                mark('node', d)
        if 'manifest.json' in fl:
            mj = read(os.path.join(d, 'manifest.json'))
            if '"manifest_version"' in mj:
                mark('extension', d)
        if 'index.html' in fl and not parts & {'templates', 'public', 'web', 'renderer',
                                               'node_modules', 'build', 'dist'}:
            mark('static', d)
        native = bool(parts & {'android', 'ios', 'windows', 'linux', 'macos', 'web'})
        if 'pom.xml' in fl:
            mark('java', d)
        for fn in files:
            p = os.path.join(d, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext == '.ino':
                mark('arduino', p)
            elif ext == '.ipynb':
                mark('notebook', p)
            elif ext == '.ned':
                mark('omnet', d)
            elif ext in ('.sln', '.vbproj', '.csproj'):
                mark('dotnet', d)
            elif ext == '.java' and not native:
                mark('java', d)
            elif ext == '.js' and d == root:
                mark('js', p)
            elif ext == '.py':
                py_files.append(p)

    for p in py_files[:400]:
        src = read(p, 60_000)
        if not src:
            continue
        if AI_WORDS.search(src):
            ai_hits += 1
        if re.search(r'^\s*(from flask import|import flask)', src, re.M) and 'Flask(' in src:
            mark('flask', p)
        if re.search(r'^\s*(from fastapi import|import fastapi)', src, re.M) and 'FastAPI(' in src:
            mark('fastapi', p)
        if re.search(r'^\s*import streamlit', src, re.M):
            mark('streamlit', p)
        if re.search(r'^\s*import gradio', src, re.M) and '.launch(' in src:
            mark('gradio', p)
        if re.search(r'^\s*(import tkinter|from tkinter|import customtkinter|from PyQt\d|'
                     r'from PySide\d|import PySimpleGUI|import kivy|from kivy|import flet|'
                     r'import wx\b)', src, re.M):
            mark('pygui', p)
        for lib, label in (('cv2', 'OpenCV'), ('tensorflow', 'TensorFlow'), ('torch', 'PyTorch'),
                           ('pandas', 'pandas'), ('openpyxl', 'Excel'), ('sklearn', 'scikit-learn'),
                           ('selenium', 'Selenium'), ('openai', 'OpenAI'), ('sqlite3', 'SQLite'),
                           ('requests', 'REST'), ('PyQt5', 'PyQt'), ('PySide6', 'Qt'),
                           ('customtkinter', 'CustomTkinter'), ('tkinter', 'Tkinter'),
                           ('rest_framework', 'DRF'), ('channels', 'WebSockets'),
                           ('matplotlib', 'matplotlib'), ('pydub', 'audio'),
                           ('moviepy', 'video')):
            if re.search(r'^\s*(import|from)\s+%s\b' % lib, src, re.M):
                stack.add(label)
    if py_files and not found:
        main = next((p for p in py_files if os.path.basename(p) in ('main.py', 'app.py')),
                    py_files[0])
        mark('python', main)
    if not found:
        mark('docs', root)

    kinds = [k for k in PRIORITY if k in found]
    primary = kinds[0]
    category = KINDS[primary][0]
    if ai_hits >= 2 or (primary in ('python', 'notebook', 'gradio') and ai_hits):
        if category in ('tools', 'docs', 'web'):
            category = 'ai' if category != 'web' else category
    for k in kinds:
        stack.add(KINDS[k][1])
    if len(stack) > 3:
        stack.discard('Python')

    rp, rtext = readme(root)
    rtitle, desc, bullets = summarize_readme(rtext)
    if desc and BOILERPLATE.match(desc):
        desc = ''
    if not rtitle or len(rtitle) > 60 or BOILERPLATE.match(rtitle) \
            or re.fullmatch(r'[a-z0-9_]+', rtitle) or rtitle.lower().startswith(('what ', 'why ')) \
            or re.sub(r'\W', '', rtitle.lower()) != re.sub(r'\W', '', slug.lower()) \
            and re.fullmatch(r'[\w\-. ]+', rtitle) and rtitle.count(' ') == 0:
        title = pretty_name(slug)
    else:
        title = rtitle
    return {
        'slug': slug,
        'title': title,
        'description': desc,
        'bullets': bullets,
        'primary': primary,
        'kinds': kinds,
        'category': category,
        'runnable': primary in RUNNABLE,
        'stack': sorted(stack, key=str.lower)[:8],
        'where': {k: os.path.relpath(v, root) for k, v in found.items()},
        'readme': rp and os.path.relpath(rp, root),
    }


if __name__ == '__main__':
    import sys
    for p in sys.argv[1:]:
        print(json.dumps(detect(p), ensure_ascii=False, indent=1))
