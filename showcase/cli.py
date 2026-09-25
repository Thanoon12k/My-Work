"""showcase — run every project, screenshot it (or mock it), build a portfolio, deploy it.

  python -m showcase clone            # clone/pull every repo listed in config.json
  python -m showcase shoot [slug...]  # detect + run + screenshot (+ mockups)
  python -m showcase build            # build the static portfolio site
  python -m showcase deploy           # upload to PythonAnywhere (token: $PA_TOKEN)
  python -m showcase all              # all of the above
  python -m showcase readme --dest D  # GitHub README + images into folder D
"""
import argparse, json, os, shutil, subprocess, sys, time, urllib.request

from . import assets, capture, detect, mockup

HERE = os.path.dirname(os.path.abspath(__file__))


def load_config(path):
    cfg = json.load(open(path, encoding='utf-8'))
    out = os.path.join(os.path.dirname(path), cfg.get('out', 'out'))
    cfg['_out'] = out
    for sub in ('repos', 'shots', 'envs', 'site'):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    return cfg


def repo_list(cfg):
    """Explicit list from config, plus everything public on the listed GitHub accounts."""
    repos = list(cfg.get('repos', []))
    for owner in cfg.get('github_owners', []):
        url = 'https://api.github.com/users/%s/repos?per_page=100&sort=pushed' % owner
        try:
            h = {'User-Agent': 'showcase'}
            if os.environ.get('GITHUB_TOKEN'):
                h['Authorization'] = 'token ' + os.environ['GITHUB_TOKEN']
            data = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=h),
                                                    timeout=30))
            for r in data:
                if not r.get('fork') and r['full_name'] not in repos:
                    repos.append(r['full_name'])
        except Exception as e:
            print('  (GitHub API unavailable for %s: %s — using config list)' % (owner, e))
    hide = set(cfg.get('skip', []))
    return [r for r in repos if r.split('/')[-1] not in hide and r not in hide]


def cmd_clone(cfg, only=None):
    root = os.path.join(cfg['_out'], 'repos')
    for full in repo_list(cfg):
        name = full.split('/')[-1]
        if only and name not in only:
            continue
        dest = os.path.join(root, name)
        if os.path.isdir(os.path.join(dest, '.git')):
            print('pull  ', full)
            subprocess.run(['git', '-C', dest, 'pull', '-q', '--ff-only'], timeout=300)
        else:
            print('clone ', full)
            subprocess.run(['git', 'clone', '-q', '--depth', '1',
                            'https://github.com/%s.git' % full, dest], timeout=600)
    for local in cfg.get('local_dirs', []):
        print('local ', local)


def project_dirs(cfg):
    root = os.path.join(cfg['_out'], 'repos')
    owners = {r.split('/')[-1]: r for r in repo_list(cfg)}
    dirs = []
    for name in sorted(os.listdir(root), key=str.lower):
        p = os.path.join(root, name)
        if os.path.isdir(p) and name in owners:
            dirs.append((name, p, 'https://github.com/' + owners[name]))
    for local in cfg.get('local_dirs', []):
        dirs.append((os.path.basename(local.rstrip('/\\')), local, None))
    return dirs


def last_commit(path):
    try:
        return subprocess.run(['git', '-C', path, 'log', '-1', '--format=%cs'],
                              capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ''


def shoot_one(cfg, browser, slug, path, url, over):
    t0 = time.time()
    p = detect.detect(path, slug)
    p.update({k: v for k, v in over.items() if not k.startswith('_')})
    p['repo'] = '' if over.get('private') else url
    p['updated'] = last_commit(path)
    outdir = os.path.join(cfg['_out'], 'shots', slug)
    shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(outdir)
    print('\n[%s] %s · %s' % (slug, p['primary'], ', '.join(p['stack'][:5])))

    shots = []
    if p['runnable'] and not over.get('no_run'):
        shots += capture.capture_live(browser, p, path, outdir,
                                      os.path.join(cfg['_out'], 'envs'),
                                      max_pages=cfg.get('max_pages', 5))
        print('    live: %d' % len(shots))
    if not shots and p['primary'] in ('django', 'flask', 'fastapi'):
        shots += capture.render_templates(p, path, outdir, browser)
        print('    templates: %d' % len(shots))
    repo_imgs = []
    for i, rel in enumerate(over.get('images', [])):      # hand-picked pictures from config
        src = os.path.join(path, rel)
        if os.path.isfile(src):
            from PIL import Image
            name = 'pick%02d.png' % (i + 1)
            im = Image.open(src).convert('RGB')
            im.save(os.path.join(outdir, name))
            repo_imgs.append({'file': name, 'kind': 'repo', 'caption': os.path.basename(rel),
                              'device': 'desktop'})
    if not repo_imgs:
        repo_imgs = assets.collect(p, path, outdir,
                                   remote=cfg.get('download_readme_images', True))
    if repo_imgs:
        print('    repo images: %d' % len(repo_imgs))
    shots += repo_imgs
    for name, html, cap in mockup.make(p, path):
        if name != 'cover' and any(s['kind'] in ('live', 'template') for s in shots):
            continue                  # real UI beats an approximation
        f = name + '.png'
        try:
            browser.html_shot(html, os.path.join(outdir, f))
            shots.append({'file': f, 'kind': 'cover' if name == 'cover' else 'mockup',
                          'device': 'desktop', 'caption': cap})
        except Exception as e:
            print('    mockup %s failed: %s' % (name, e))
    p['shots'] = shots
    p['seconds'] = round(time.time() - t0, 1)
    print('    -> %d image(s) in %.0fs' % (len(shots), p['seconds']))
    return p


def cmd_shoot(cfg, only=None):
    db_path = os.path.join(cfg['_out'], 'projects.json')
    db = {}
    if os.path.exists(db_path):
        db = {p['slug']: p for p in json.load(open(db_path, encoding='utf-8'))}
    browser = capture.Browser()
    overrides = cfg.get('projects', {})
    try:
        for slug, path, url in project_dirs(cfg):
            if only and slug not in only:
                continue
            if overrides.get(slug, {}).get('hide'):
                continue
            try:
                db[slug] = shoot_one(cfg, browser, slug, path, url, overrides.get(slug, {}))
            except Exception as e:
                print('  ! %s failed: %s' % (slug, e))
            json.dump(list(db.values()), open(db_path, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
    finally:
        browser.close()


def main(argv=None):
    ap = argparse.ArgumentParser(prog='showcase', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['clone', 'shoot', 'build', 'deploy', 'readme', 'all'])
    ap.add_argument('only', nargs='*', help='limit to these project slugs')
    ap.add_argument('--config', default=os.path.join(HERE, 'config.json'))
    ap.add_argument('--user', help='PythonAnywhere username (default: config deploy.user)')
    ap.add_argument('--dest', default='.', help='readme: folder to write README.md + docs/ into')
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    if a.command in ('clone', 'all'):
        cmd_clone(cfg, a.only)
    if a.command in ('shoot', 'all'):
        cmd_shoot(cfg, a.only)
    if a.command in ('build', 'all'):
        from . import site
        site.build(cfg)
    if a.command == 'readme':
        from . import readme
        readme.build(cfg, os.path.abspath(a.dest))
    if a.command in ('deploy', 'all'):
        from . import pa
        pa.deploy(cfg, a.user)


if __name__ == '__main__':
    main()
