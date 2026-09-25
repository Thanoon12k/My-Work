"""Build the static portfolio (index.html + webp images + favicon) from out/projects.json."""
import html, json, os, shutil

CATS = [('web', 'ويب'), ('mobile', 'موبايل'), ('desktop', 'ديسكتوب'), ('hw', 'أجهزة و IoT'),
        ('ai', 'ذكاء اصطناعي'), ('sim', 'شبكات ومحاكاة'), ('tools', 'أدوات'),
        ('docs', 'أبحاث وملاحظات')]
KIND_LABEL = {'live': 'لقطة حقيقية', 'upload': 'لقطة حقيقية', 'template': 'من قوالب المشروع', 'repo': 'صور المشروع',
              'mockup': 'تصور من الكود', 'cover': 'غلاف'}
KIND_RANK = {'live': 0, 'repo': 1, 'template': 2, 'mockup': 3, 'cover': 4}

FAVICON_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect x="7" y="3" width="54" height="54" rx="14" fill="#16130D"/>
<rect x="3" y="7" width="54" height="54" rx="14" fill="#FFC93C" stroke="#16130D" stroke-width="4"/>
<path d="M22 22 L13 34 L22 46" fill="none" stroke="#16130D" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M38 22 L47 34 L38 46" fill="none" stroke="#16130D" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M33 19 L27 49" stroke="#FF5C39" stroke-width="6" stroke-linecap="round"/>
</svg>'''


def webp(src, dst, width):
    from PIL import Image
    im = Image.open(src)
    im = im.convert('RGB')
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(dst, 'WEBP', quality=80, method=5)
    return im.size


def favicons(outdir):
    open(os.path.join(outdir, 'favicon.svg'), 'w', encoding='utf-8').write(FAVICON_SVG)
    try:
        from .capture import Browser
        b = Browser()
        try:
            page = ('<html><body style="margin:0;background:transparent">'
                    '<div style="width:180px;height:180px">%s</div></body></html>'
                    % FAVICON_SVG.replace('<svg ', '<svg width="180" height="180" '))
            pg = b.page(180, 180)
            pg.set_content(page)
            png = os.path.join(outdir, 'apple-touch-icon.png')
            pg.screenshot(path=png, omit_background=True)
            pg.context.close()
        finally:
            b.close()
        from PIL import Image
        im = Image.open(png).convert('RGBA')
        im.resize((32, 32), Image.LANCZOS).save(os.path.join(outdir, 'favicon-32.png'))
        im.save(os.path.join(outdir, 'favicon.ico'), sizes=[(16, 16), (32, 32), (48, 48)])
    except Exception as e:
        print('  (png favicons skipped: %s)' % e)


def build(cfg):
    out = cfg['_out']
    site = os.path.join(out, 'site')
    shutil.rmtree(site, ignore_errors=True)
    os.makedirs(os.path.join(site, 'img'))
    projects = json.load(open(os.path.join(out, 'projects.json'), encoding='utf-8'))
    over = cfg.get('projects', {})
    data = []
    for p in projects:
        o = over.get(p['slug'], {})
        if o.get('hide') or not p.get('shots'):
            continue
        p.update({k: v for k, v in o.items() if not k.startswith('_')})
        shots = sorted(p['shots'], key=lambda s: KIND_RANK.get(s['kind'], 9))
        real = [s for s in shots if s['kind'] != 'cover']
        cover = [s for s in shots if s['kind'] == 'cover']
        # the generated cover is only the headline image when nothing better exists
        shots = real + cover if not real else real + cover[:1]
        imgs = []
        d = os.path.join(site, 'img', p['slug'])
        os.makedirs(d, exist_ok=True)
        for i, s in enumerate(shots[:8]):
            src = os.path.join(out, 'shots', p['slug'], s['file'])
            if not os.path.exists(src):
                continue
            base = '%02d' % i
            w, h = webp(src, os.path.join(d, base + '.webp'), 1600)
            if i == 0:
                webp(src, os.path.join(d, 'thumb.webp'), 720)
            imgs.append({'src': 'img/%s/%s.webp' % (p['slug'], base), 'kind': s['kind'],
                         'w': w, 'h': h, 'device': s.get('device', 'desktop')})
        if not imgs:
            continue
        stack, seen = [], set()
        for x in p.get('stack', []):
            if x.lower() not in seen:
                seen.add(x.lower())
                stack.append(x)
        p['stack'] = stack
        data.append({
            'slug': p['slug'], 'title': p.get('title_ar') or p['title'],
            'en': p['title'] if p.get('title_ar') else '',
            'desc': p.get('description_ar') or p.get('description') or '',
            'bullets': p.get('bullets', [])[:5], 'cat': p.get('category', 'tools'),
            'stack': p.get('stack', [])[:6], 'repo': p.get('repo'),
            'live_url': p.get('live_url'), 'updated': p.get('updated', ''),
            'kind': imgs[0]['kind'], 'thumb': 'img/%s/thumb.webp' % p['slug'], 'imgs': imgs,
            'featured': p.get('featured', 99),
        })
    data.sort(key=lambda x: (x['featured'], KIND_RANK.get(x['kind'], 9),
                             -int((x['updated'] or '0').replace('-', '') or 0)))
    favicons(site)
    s = cfg['site']
    me = dict(cfg.get('profile', {}))
    if me.get('photo'):
        from PIL import Image
        src = os.path.join(os.path.dirname(cfg['_out']), me['photo'])
        im = Image.open(src).convert('RGB')
        im.thumbnail((600, 600))
        im.save(os.path.join(site, 'img', 'me.webp'), 'WEBP', quality=85)
        me['photo'] = 'img/me.webp'
    counts = {c: sum(1 for x in data if x['cat'] == c) for c, _ in CATS}
    chips = '<button class="chip on" data-f="all">الكل <em>%d</em></button>' % len(data) + ''.join(
        '<button class="chip" data-f="%s">%s <em>%d</em></button>' % (c, l, counts[c])
        for c, l in CATS if counts[c])
    live = sum(1 for x in data if x['kind'] in ('live', 'template', 'repo'))
    page = TEMPLATE
    for k, v in {
        '{{TITLE}}': html.escape(s['title']), '{{NAME}}': html.escape(me.get('name', '')),
        '{{NAME_EN}}': html.escape(me.get('name_en', '')), '{{ROLE}}': html.escape(me.get('role', '')),
        '{{PHOTO}}': me.get('photo', 'favicon.svg'),
        '{{ME}}': json.dumps(me, ensure_ascii=False).replace('</', '<\\/'),
        '{{TAGLINE}}': html.escape(s['tagline']), '{{CHIPS}}': chips,
        '{{N}}': str(len(data)), '{{LIVE}}': str(live), '{{CATS}}': str(sum(1 for v in
                                                                            counts.values() if v)),
        '{{WA}}': s.get('whatsapp', '#'),
        '{{GH}}': s.get('github', '#'), '{{TEL}}': s.get('phone', ''),
        '{{OG}}': data[0]['thumb'] if data else '',
        '{{DATA}}': json.dumps(data, ensure_ascii=False).replace('</', '<\\/'),
        '{{CATMAP}}': json.dumps(dict(CATS), ensure_ascii=False),
        '{{KINDMAP}}': json.dumps(KIND_LABEL, ensure_ascii=False),
    }.items():
        page = page.replace(k, v)
    open(os.path.join(site, 'index.html'), 'w', encoding='utf-8').write(page)
    json.dump(data, open(os.path.join(site, 'data.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)
    json.dump(me, open(os.path.join(site, 'profile.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)
    shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'server.py'), site)
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(site) for f in fs)
    print('site: %d projects, %.1f MB -> %s' % (len(data), size / 1e6, site))
    return site


TEMPLATE = r'''<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}}</title>
<meta name="description" content="{{TAGLINE}}">
<meta property="og:title" content="{{TITLE}}">
<meta property="og:description" content="{{TAGLINE}}">
<meta property="og:image" content="{{PHOTO}}">
<meta name="theme-color" content="#FFC93C">
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="icon" href="favicon-32.png" sizes="32x32" type="image/png">
<link rel="alternate icon" href="favicon.ico">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>
:root{--cream:#FFF6EA;--paper:#fff;--ink:#16130D;--dim:#5C554A;--faint:#8E8578;--gold:#FFC93C;
 --coral:#FF5C39;--teal:#12B99C;--blue:#4361EE;--lilac:#9B7EDE;--line:3px solid var(--ink);
 --pop:-6px 6px 0 var(--ink);--pop-sm:-4px 4px 0 var(--ink)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--cream:#16130D;--paper:#221E17;
 --ink:#FFF6EA;--dim:#D7CDBE;--faint:#A89C8B}}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--cream);color:var(--ink);font-family:Cairo,'Segoe UI',Tahoma,sans-serif;line-height:1.7;overflow-x:hidden}
a{color:inherit;text-decoration:none}
.wrap{max-width:1200px;margin:0 auto;padding:0 16px}
nav{position:sticky;top:0;z-index:40;background:var(--cream);border-bottom:var(--line)}
.nav{display:flex;align-items:center;gap:16px;height:68px}
.logo{display:flex;align-items:center;gap:10px;font-weight:900;font-size:18px}
.logo img{width:40px;height:40px}
.nav .sp{flex:1}
.btn{display:inline-flex;align-items:center;gap:8px;font-weight:700;font-size:15px;border:var(--line);
 border-radius:14px;padding:9px 18px;background:var(--gold);color:#16130D;box-shadow:var(--pop-sm);transition:.12s;cursor:pointer}
.btn:hover{transform:translate(2px,-2px);box-shadow:var(--pop)}
.btn.white{background:var(--paper);color:var(--ink)}
header{padding:56px 0 30px}
.tag{display:inline-block;font-size:14px;font-weight:700;border:var(--line);border-radius:100px;padding:5px 18px;
 background:var(--paper);box-shadow:var(--pop-sm);margin-bottom:22px}
h1{font-size:clamp(34px,6vw,62px);line-height:1.2;font-weight:900;max-width:820px}
h1 mark{background:var(--gold);color:#16130D;padding:0 12px;border-radius:14px;border:var(--line);box-shadow:var(--pop-sm)}
.lead{font-size:clamp(16px,2.2vw,19px);color:var(--dim);max-width:680px;margin:20px 0 28px}
.stats{display:flex;gap:14px;flex-wrap:wrap}
.stat{border:var(--line);border-radius:18px;background:var(--paper);padding:10px 20px;box-shadow:var(--pop-sm)}
.stat b{font-size:28px;font-weight:900;display:block;line-height:1.2}.stat span{font-size:13px;color:var(--dim)}
.tools{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:34px 0 22px}
.chip{font:700 14px Cairo,sans-serif;border:var(--line);border-radius:100px;padding:6px 16px;background:var(--paper);
 color:var(--ink);cursor:pointer}
.chip em{font-style:normal;opacity:.55;font-size:12px}
.chip.on{background:var(--ink);color:var(--cream)}
.search{flex:1;min-width:200px;font:600 15px Cairo,sans-serif;border:var(--line);border-radius:14px;padding:8px 16px;
 background:var(--paper);color:var(--ink)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:28px;padding-bottom:70px}
@media (max-width:420px){.grid{grid-template-columns:1fr}}
.card{background:var(--paper);border:var(--line);border-radius:22px;box-shadow:var(--pop);overflow:hidden;cursor:pointer;
 display:flex;flex-direction:column;transition:.15s}
.card:hover{transform:translate(3px,-3px);box-shadow:-9px 9px 0 var(--ink)}
.thumb{aspect-ratio:16/10;background:#EFE6D8;border-bottom:var(--line);position:relative;overflow:hidden}
.thumb img{width:100%;height:100%;object-fit:cover;object-position:top center;display:block}
.thumb.mobile img{object-fit:contain;background:#EFE6D8}
.kind{position:absolute;top:12px;right:12px;font-size:12px;font-weight:800;border:2px solid #16130D;border-radius:100px;
 padding:1px 11px;background:#fff;color:#16130D}
.kind.live{background:var(--teal);color:#fff}.kind.repo{background:var(--gold)}
.kind.mockup,.kind.cover{background:#fff}
.count{position:absolute;bottom:10px;left:12px;font-size:12px;font-weight:800;background:#16130Dcc;color:#fff;
 border-radius:10px;padding:1px 9px}
.body{padding:16px 18px 18px;display:flex;flex-direction:column;gap:8px;flex:1}
.body h3{font-size:19px;font-weight:900;line-height:1.35}
.body h3 small{display:block;font-size:12px;color:var(--faint);font-weight:600;direction:ltr;text-align:right}
.body p{font-size:14px;color:var(--dim);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.stack{display:flex;flex-wrap:wrap;gap:6px;margin-top:auto;padding-top:6px}
.stack span{font-size:11.5px;font-weight:700;border:2px solid var(--ink);border-radius:100px;padding:0 10px;direction:ltr}
.empty{display:none;text-align:center;padding:60px 0;color:var(--dim);font-weight:700}
/* modal */
.modal{position:fixed;inset:0;z-index:60;background:#16130Dd9;display:none;align-items:center;justify-content:center;padding:16px}
.modal.open{display:flex}
.box{background:var(--cream);border:var(--line);border-radius:24px;width:min(1100px,100%);max-height:94vh;overflow:auto;
 box-shadow:var(--pop)}
.viewer{position:relative;background:#16130D;display:flex;align-items:center;justify-content:center;min-height:240px}
.viewer img{max-width:100%;max-height:62vh;display:block}
.arrow{position:absolute;top:50%;transform:translateY(-50%);width:44px;height:44px;border-radius:50%;border:var(--line);
 background:var(--gold);font:900 22px Cairo;cursor:pointer;color:#16130D}
.arrow.prev{right:12px}.arrow.next{left:12px}
.close{position:absolute;top:12px;left:12px;width:40px;height:40px;border-radius:12px;border:var(--line);background:#fff;
 font:900 20px Cairo;cursor:pointer;color:#16130D;z-index:2}
.strip{display:flex;gap:8px;padding:10px 14px;overflow-x:auto;background:#16130D}
.strip img{height:58px;border-radius:8px;border:2px solid transparent;opacity:.6;cursor:pointer}
.strip img.on{border-color:var(--gold);opacity:1}
.info{padding:20px 24px 26px;display:grid;gap:10px}
.info h2{font-size:26px;font-weight:900;line-height:1.3}
.info .meta{font-size:13px;color:var(--faint);font-weight:700}
.info ul{padding-right:20px;color:var(--dim);font-size:14.5px}
.note{font-size:12.5px;color:var(--faint)}
.acts{display:flex;gap:10px;flex-wrap:wrap;margin-top:6px}
section.contact{border-top:var(--line);padding:60px 0;text-align:center}
section.contact h2{font-size:clamp(26px,4vw,40px);font-weight:900;margin-bottom:10px}
section.contact p{color:var(--dim);margin-bottom:24px}
footer{border-top:var(--line);padding:22px 0;font-size:13px;color:var(--faint);text-align:center}
.av{width:40px;height:40px;border-radius:50%;border:var(--line);object-fit:cover}
.lnk{font-weight:700;font-size:15px}.lnk:hover{color:var(--coral)}
@media (max-width:560px){.lnk{display:none}}
.hero{display:flex;align-items:center;gap:48px}
.me{position:relative;flex:none;width:230px;height:230px}
.me img{width:100%;height:100%;object-fit:cover;border-radius:36px;border:var(--line);box-shadow:-10px 10px 0 var(--ink);
 background:var(--gold)}
.me .dot{position:absolute;bottom:14px;left:-6px;width:30px;height:30px;border-radius:50%;background:var(--teal);border:var(--line)}
.intro{min-width:0}
h1 small{display:block;font-size:clamp(15px,2vw,19px);color:var(--faint);font-weight:700;direction:ltr;text-align:right;margin-top:4px}
.loc{font-weight:700;color:var(--dim);margin:-14px 0 20px;font-size:15px}.loc:empty{display:none}
.acts{display:flex;gap:10px;flex-wrap:wrap}
header .stats{margin-top:34px}
@media (max-width:760px){.hero{flex-direction:column;align-items:flex-start;gap:26px}.me{width:150px;height:150px}}
h2.sec{font-size:clamp(26px,4vw,38px);font-weight:900;margin-top:10px}
h2.sec small{display:block;font-size:15px;color:var(--faint);font-weight:700}
.about{border-top:var(--line);padding:56px 0}
.cols{display:grid;grid-template-columns:1.3fr 1fr;gap:26px;margin-top:22px}
@media (max-width:820px){.cols{grid-template-columns:1fr}}
.side{display:grid;gap:26px;align-content:start}
.panel{background:var(--paper);border:var(--line);border-radius:22px;box-shadow:var(--pop);padding:20px 22px}
.panel h3{font-size:19px;font-weight:900;margin-bottom:10px}
.panel p,.panel li{color:var(--dim);font-size:14.5px}
.panel ul{padding-right:18px;margin-top:8px}
.tl{list-style:none;display:grid;gap:18px}
.tl li{border-right:4px solid var(--gold);padding-right:14px}
.tl b{display:block;color:var(--ink);font-size:16px}.tl em{font-style:normal;font-size:12.5px;font-weight:800;color:var(--faint)}
.hl{padding:10px 0 30px}
.hls{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:20px;margin-top:18px}
.hls div{background:var(--paper);border:var(--line);border-radius:20px;box-shadow:var(--pop-sm);padding:16px 18px}
.hls i{font-style:normal;font-size:30px;display:block}.hls b{display:block;font-size:17px;margin:4px 0}
.hls p{font-size:14px;color:var(--dim)}
.skills{display:flex;flex-wrap:wrap;gap:7px}
.skills span{font-size:13px;font-weight:700;border:2px solid var(--ink);border-radius:100px;padding:1px 12px;direction:ltr}
</style>
</head>
<body>
<nav><div class="wrap nav">
 <a class="logo" href="#"><img class="av" id="navPhoto" src="{{PHOTO}}" alt=""><span id="navName">{{NAME}}</span></a>
 <span class="sp"></span>
 <a class="lnk" href="#about">عني</a><a class="lnk" href="#work">مشاريعي</a>
 <a class="btn" href="{{WA}}" target="_blank" rel="noopener">تواصل</a>
</div></nav>

<header><div class="wrap hero">
 <div class="me"><img id="photo" src="{{PHOTO}}" alt="{{NAME}}"><span class="dot" title="متاح للعمل"></span></div>
 <div class="intro">
  <span class="tag" id="role">{{ROLE}}</span>
  <h1><span id="name">{{NAME}}</span><small id="nameEn">{{NAME_EN}}</small></h1>
  <p class="lead" id="bio">{{TAGLINE}}</p>
  <p class="loc" id="loc"></p>
  <div class="acts">
   <a class="btn" href="#work">شوف مشاريعي ↓</a>
   <a class="btn white" href="{{WA}}" target="_blank" rel="noopener">واتساب</a>
   <a class="btn white" href="{{GH}}" target="_blank" rel="noopener">GitHub</a>
  </div>
 </div>
</div>
<div class="wrap stats" id="stats">
  <div class="stat"><b id="sN">{{N}}</b><span>مشروع</span></div>
  <div class="stat"><b id="sL">{{LIVE}}</b><span>بلقطات حقيقية</span></div>
  <div class="stat"><b id="sC">{{CATS}}</b><span>مجالات</span></div>
</div></header>

<section class="hl"><div class="wrap"><h2 class="sec">شنو أقدّم</h2><div class="hls" id="hls"></div></div></section>

<main class="wrap" id="work">
 <h2 class="sec">مشاريعي <small>كل مشروع مشغّل ومصوّر تلقائياً</small></h2>
 <div class="tools"><span id="chips" style="display:contents">{{CHIPS}}</span><input class="search" id="q" type="search" placeholder="ابحث: Flutter، Django، عيادة…"></div>
 <div class="grid" id="grid"></div>
 <div class="empty" id="empty">ماكو مشروع يطابق البحث.</div>
</main>

<section class="about" id="about"><div class="wrap">
 <h2 class="sec">عني</h2>
 <div class="cols">
  <div class="panel"><h3>الخبرة</h3><ol class="tl" id="exp"></ol></div>
  <div class="side">
   <div class="panel"><h3>الدراسة</h3><p id="edu"></p><ul id="train"></ul></div>
   <div class="panel"><h3>المهارات</h3><div class="skills" id="skills"></div></div>
   <div class="panel"><h3>اللغات</h3><p id="langs"></p></div>
  </div>
 </div>
</div></section>

<section class="contact"><div class="wrap">
 <h2>عندك فكرة؟ خلّينا نبنيها</h2>
 <p>موقع، تطبيق، نظام إدارة، أو ربط جهاز — احچيلي عنها.</p>
 <div class="acts" style="justify-content:center">
  <a class="btn" href="{{WA}}" target="_blank" rel="noopener">واتساب</a>
  <a class="btn white" href="tel:{{TEL}}">اتصال</a>
  <a class="btn white" id="mail" href="#">إيميل</a>
  <a class="btn white" href="{{GH}}" target="_blank" rel="noopener">GitHub</a>
 </div>
</div></section>
<footer>© <span id="fName">{{NAME}}</span> · اللقطات مأخوذة تلقائياً بتشغيل كل مشروع — والمشاريع اللي ما عدها واجهة انرسمت من كودها.</footer>

<div class="modal" id="modal" role="dialog" aria-modal="true">
 <div class="box">
  <div class="viewer"><button class="close" id="x" aria-label="إغلاق">✕</button>
   <button class="arrow prev" id="prev" aria-label="السابق">›</button><img id="big" alt="">
   <button class="arrow next" id="next" aria-label="التالي">‹</button></div>
  <div class="strip" id="strip"></div>
  <div class="info" id="info"></div>
 </div>
</div>

<script>
const P=/*DATA*/{{DATA}}/*END*/, ME=/*ME*/{{ME}}/*MEEND*/, CAT={{CATMAP}}, KIND={{KINDMAP}};
const $=s=>document.querySelector(s), esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let filter='all', q='';
function draw(){
 const k=q.trim().toLowerCase();
 const list=P.filter(p=>(filter==='all'||p.cat===filter)&&(!k||[p.title,p.en,p.desc,p.stack.join(' '),p.slug].join(' ').toLowerCase().includes(k)));
 $('#grid').innerHTML=list.map(p=>`<article class="card" data-s="${p.slug}" tabindex="0">
  <div class="thumb ${p.imgs[0].device==='mobile'?'mobile':''}"><img loading="lazy" src="${p.thumb}" alt="${esc(p.title)}">
  <span class="kind ${p.kind}">${KIND[p.kind]}</span>${p.imgs.length>1?`<span class="count">${p.imgs.length} صور</span>`:''}</div>
  <div class="body"><h3>${esc(p.title)}${p.en?`<small>${esc(p.en)}</small>`:''}</h3>
  <p dir="auto">${esc(p.desc||CAT[p.cat])}</p><div class="stack">${p.stack.map(s=>`<span>${esc(s)}</span>`).join('')}</div></div></article>`).join('');
 $('#empty').style.display=list.length?'none':'block';
}
(function(){const t=(id,v)=>{const e=document.getElementById(id);if(e&&v!=null)e.textContent=v};
 t('name',ME.name);t('navName',ME.name);t('fName',ME.name);t('nameEn',ME.name_en);t('role',ME.role);
 t('bio',ME.bio);t('loc',ME.location?'📍 '+ME.location:'');t('edu',ME.education);t('langs',ME.languages);
 if(ME.photo){$('#photo').src=ME.photo;$('#navPhoto').src=ME.photo}
 if(ME.email)$('#mail').href='mailto:'+ME.email;else $('#mail').remove();
 $('#exp').innerHTML=(ME.experience||[]).map(x=>`<li><b>${esc(x.title)}</b><em>${esc(x.years)}</em><p>${esc(x.text)}</p></li>`).join('');
 $('#train').innerHTML=(ME.training||[]).map(x=>`<li>${esc(x)}</li>`).join('');
 $('#hls').innerHTML=(ME.highlights||[]).map(x=>`<div><i>${esc(x.icon)}</i><b>${esc(x.title)}</b><p>${esc(x.text)}</p></div>`).join('');
 if(!(ME.highlights||[]).length)$('.hl').remove();
 $('#skills').innerHTML=(ME.skills||[]).map(x=>`<span>${esc(x)}</span>`).join('');
 const st=$('#stats');(ME.stats||[]).forEach(([v,l])=>{st.insertAdjacentHTML('beforeend',`<div class="stat"><b>${esc(v)}</b><span>${esc(l)}</span></div>`)});
 if(ME.name)document.title=ME.name+(ME.role?' — '+ME.role:'');})();
(function(){const n={};P.forEach(p=>n[p.cat]=(n[p.cat]||0)+1);
 $('#sN').textContent=P.length;$('#sC').textContent=Object.keys(n).length;
 $('#sL').textContent=P.filter(p=>['live','upload','template','repo'].includes(p.kind)).length;
 $('#chips').innerHTML=`<button class="chip on" data-f="all">الكل <em>${P.length}</em></button>`+
  Object.keys(CAT).filter(c=>n[c]).map(c=>`<button class="chip" data-f="${c}">${CAT[c]} <em>${n[c]}</em></button>`).join('');})();
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{(function(){const t=(id,v)=>{const e=document.getElementById(id);if(e&&v!=null)e.textContent=v};
 t('name',ME.name);t('navName',ME.name);t('fName',ME.name);t('nameEn',ME.name_en);t('role',ME.role);
 t('bio',ME.bio);t('loc',ME.location?'📍 '+ME.location:'');t('edu',ME.education);t('langs',ME.languages);
 if(ME.photo){$('#photo').src=ME.photo;$('#navPhoto').src=ME.photo}
 if(ME.email)$('#mail').href='mailto:'+ME.email;else $('#mail').remove();
 $('#exp').innerHTML=(ME.experience||[]).map(x=>`<li><b>${esc(x.title)}</b><em>${esc(x.years)}</em><p>${esc(x.text)}</p></li>`).join('');
 $('#train').innerHTML=(ME.training||[]).map(x=>`<li>${esc(x)}</li>`).join('');
 $('#hls').innerHTML=(ME.highlights||[]).map(x=>`<div><i>${esc(x.icon)}</i><b>${esc(x.title)}</b><p>${esc(x.text)}</p></div>`).join('');
 if(!(ME.highlights||[]).length)$('.hl').remove();
 $('#skills').innerHTML=(ME.skills||[]).map(x=>`<span>${esc(x)}</span>`).join('');
 const st=$('#stats');(ME.stats||[]).forEach(([v,l])=>{st.insertAdjacentHTML('beforeend',`<div class="stat"><b>${esc(v)}</b><span>${esc(l)}</span></div>`)});
 if(ME.name)document.title=ME.name+(ME.role?' — '+ME.role:'');})();
(function(){const n={};P.forEach(p=>n[p.cat]=(n[p.cat]||0)+1);
 $('#sN').textContent=P.length;$('#sC').textContent=Object.keys(n).length;
 $('#sL').textContent=P.filter(p=>['live','upload','template','repo'].includes(p.kind)).length;
 $('#chips').innerHTML=`<button class="chip on" data-f="all">الكل <em>${P.length}</em></button>`+
  Object.keys(CAT).filter(c=>n[c]).map(c=>`<button class="chip" data-f="${c}">${CAT[c]} <em>${n[c]}</em></button>`).join('');})();
document.querySelectorAll('.chip').forEach(x=>x.classList.remove('on'));c.classList.add('on');filter=c.dataset.f;draw()});
$('#q').oninput=e=>{q=e.target.value;draw()};
let cur=null, idx=0;
function show(i){idx=(i+cur.imgs.length)%cur.imgs.length;$('#big').src=cur.imgs[idx].src;
 document.querySelectorAll('#strip img').forEach((im,j)=>im.classList.toggle('on',j===idx));
 $('#note').textContent=KIND[cur.imgs[idx].kind]+(cur.imgs[idx].kind==='mockup'?' — تصور تقريبي مبني من نصوص وأيقونات الكود نفسه':cur.imgs[idx].kind==='template'?' — قوالب المشروع الأصلية بدون بيانات':cur.imgs[idx].kind==='cover'?' — صورة معبّرة عن المشروع':'');}
function open_(slug){cur=P.find(p=>p.slug===slug);if(!cur)return;
 $('#strip').innerHTML=cur.imgs.map((im,j)=>`<img src="${im.src}" data-i="${j}" alt="">`).join('');
 $('#strip').style.display=cur.imgs.length>1?'flex':'none';
 $('#prev').style.display=$('#next').style.display=cur.imgs.length>1?'block':'none';
 $('#info').innerHTML=`<h2>${esc(cur.title)}</h2><div class="meta">${esc(CAT[cur.cat])}${cur.en?' · '+esc(cur.en):''}${cur.updated?' · آخر تحديث '+cur.updated:''}</div>
  ${cur.desc?`<p dir="auto">${esc(cur.desc)}</p>`:''}${cur.bullets.length?`<ul dir="auto">${cur.bullets.map(b=>`<li>${esc(b)}</li>`).join('')}</ul>`:''}
  <div class="stack">${cur.stack.map(s=>`<span>${esc(s)}</span>`).join('')}</div><div class="note" id="note"></div>
  <div class="acts">${cur.repo?`<a class="btn white" href="${cur.repo}" target="_blank" rel="noopener">الكود على GitHub</a>`:''}
  ${cur.live_url?`<a class="btn" href="${cur.live_url}" target="_blank" rel="noopener">جرّبه مباشرة</a>`:''}
  <a class="btn" href="{{WA}}?text=${encodeURIComponent('أريد مشروع مثل: '+cur.title)}" target="_blank" rel="noopener">أريد مثله</a></div>`;
 $('#modal').classList.add('open');document.body.style.overflow='hidden';show(0);history.replaceState(null,'','#'+slug);}
function close_(){$('#modal').classList.remove('open');document.body.style.overflow='';history.replaceState(null,'',location.pathname);}
$('#grid').onclick=e=>{const c=e.target.closest('.card');if(c)open_(c.dataset.s)};
$('#grid').onkeydown=e=>{if(e.key==='Enter'){const c=e.target.closest('.card');if(c)open_(c.dataset.s)}};
$('#strip').onclick=e=>{if(e.target.dataset.i)show(+e.target.dataset.i)};
$('#prev').onclick=()=>show(idx-1);$('#next').onclick=()=>show(idx+1);$('#x').onclick=close_;
$('#modal').onclick=e=>{if(e.target.id==='modal')close_()};
addEventListener('keydown',e=>{if(!cur||!$('#modal').classList.contains('open'))return;if(e.key==='Escape')close_();
 if(e.key==='ArrowLeft')show(idx+1);if(e.key==='ArrowRight')show(idx-1)});
draw();if(location.hash)open_(location.hash.slice(1));
</script>
</body>
</html>'''
