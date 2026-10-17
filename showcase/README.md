# showcase — معرض أعمال يبني نفسه

أداة تشغّل كل مشاريعك، تصوّرها، وترفع معرض أعمال جاهز على PythonAnywhere.

```
clone  →  shoot  →  build  →  deploy
```

| المرحلة | شنو تسوي |
|---|---|
| `clone` | تسحب كل الريبوهات المكتوبة بـ `config.json` (وأي ريبو عام بحساب GitHub إذا الـ API متاح) |
| `shoot` | تكتشف نوع كل مشروع، تشغّله، وتاخذ له لقطات — أو تصنع له صورة تقريبية |
| `build` | تبني موقع ثابت (`out/site`) بصيغة webp مع أيقونة تبويب |
| `deploy` | ترفع الموقع لـ PythonAnywhere وتضبط الـ web app وتعيد تحميله |

## كيف تنجاب الصور — بالترتيب

1. **لقطة حقيقية** — المشروع يشتغل فعلاً والمتصفح يتجول بصفحاته:
   Django (مع `migrate` وحساب تجريبي `demo / Demo12345!` يسجل دخول تلقائياً)،
   Flask، FastAPI، Streamlit، Gradio، React/Vite/Next (`npm install` ثم dev server)،
   مواقع HTML، وإضافات كروم (صفحة الـ popup). لقطة ديسكتوب + لقطة موبايل.
2. **من قوالب المشروع** — إذا سيرفر Django/Flask ما اشتغل، ترسم قوالب HTML الأصلية بدون بيانات.
3. **صور المشروع** — صور الـ README، مجلدات screenshots، ومخططات الـ notebooks.
4. **تصور من الكود** — للمشاريع اللي ما تشتغل بالمتصفح:
   - Flutter ← شاشات موبايل مبنية من نصوص `Text()` والأيقونات والألوان الحقيقية بالكود
   - Tkinter / PyQt / WinForms / Electron ← نافذة ديسكتوب من أسماء الأزرار والحقول
   - Arduino / OMNeT++ / Java / سكربتات ← محرر كود + Serial Monitor أو Output
5. **غلاف** — صورة معبّرة تنرسم لكل مشروع (أيقونة حسب موضوعه: عيادة، صوت، شبكات، حساسات…).

الموقع يكتب نوع كل صورة بوضوح (لقطة حقيقية / تصور من الكود…) — حتى محد يحس إنها خداع.

## التشغيل

```bash
pip install playwright pillow jinja2
python -m playwright install chromium

# التوكن ما ينحفظ بالريبو أبداً
set PA_TOKEN=xxxxxxxx          # Windows cmd
$env:PA_TOKEN="xxxxxxxx"       # PowerShell
export PA_TOKEN=xxxxxxxx       # Linux/mac

python -m showcase all                     # كلشي
python -m showcase shoot Ideas-Store       # مشروع واحد بس
python -m showcase build
python -m showcase deploy --user make1it
```

## لوحة الإدارة — `/admin`

بعد الرفع تفتح `https://make1it.pythonanywhere.com/admin` وتدخل بكلمة السر
(تنطبع مرة وحدة بأول `deploy`، وتقدر تغيّرها من نفس اللوحة). منها تقدر:

- **تضيف صور/سكرينات** لأي مشروع: تختاره من القائمة، وتسحب الصور أو تلصقها (Ctrl+V)، وتضغط حفظ.
  الصور المرفوعة تصير أول صور المشروع وتتحول تلقائياً لـ webp.
- **تنشئ مشروع جديد** مباشرة من الموقع: تختار «➕ مشروع جديد» وتكتب الاسم والوصف والتصنيف وترفع صوره.
- **تعدّل** الاسم والوصف والتصنيف والتقنيات والروابط والترتيب، أو **تخفي** مشروع.
- **تخفي صورة** مولّدة ما عجبتك، أو **تحذف** صورة رفعتها، أو تخلّي صورة هي الأولى.

كل شي تضيفه من اللوحة ينحفظ بمجلد منفصل على السيرفر (`/home/<user>/portfolio_data`)،
فإعادة `deploy` تحدّث اللقطات المولّدة بس وما تمسح شي من إضافاتك.

## الإعدادات — `config.json`

- `repos`: الريبوهات (`owner/name`). `github_owners`: يضيف كل ريبو عام تلقائياً.
- `local_dirs`: مجلدات مشاريع على جهازك مو على GitHub.
- `projects.<slug>`: تعديلات لكل مشروع:
  `title_ar`, `description_ar`, `category` (`web mobile desktop hw ai sim tools docs`),
  `featured` (رقم الترتيب)، `live_url`، `no_run`، `hide`.
- `deploy`: `user`، `remote_dir`، و`remove_old` (مجلدات قديمة تنمسح بالسيرفر).

كل شي يتولد داخل `out/` (مو بالريبو): الريبوهات، البيئات، اللقطات، والموقع.

## مشروع API خفيف للوكلاء — أقل توكنات، بدون MCP إضافي

النسخة الجديدة تضيف REST API إلى Flask الحالي بدون تغيير تصميم الموقع أو لوحة الإدارة.
الـ API **مقفلة افتراضياً** حتى يتم إعداد مفتاح سري على الخادم.
محتوى `portfolio_data/custom.json` الحالي يبقى كما هو خارج مجلد النشر.

### تفعيل المفتاح (مرة واحدة فقط)

داخل PythonAnywhere Bash console، نفّذ (المفتاح يبقى خارج GitHub):

```bash
mkdir -p ~/portfolio_data
python3 -c "import secrets; print(secrets.token_urlsafe(32))" > ~/portfolio_data/api_token
chmod 600 ~/portfolio_data/api_token
```

احتفظ بنسخة آمنة من المفتاح الذي أنشأته لاستخدامه في أداة التحديث. لا تشارك المفتاح في المحادثات أو GitHub أو ملفات الواجهة. بدلاً من الملف يمكن ضبط المتغير `SHOWCASE_API_TOKEN` على السيرفر. احذف الملف أو غيّر قيمته لإبطال المفتاح فوراً. بعد تحديث الملفات شغّل `python -m showcase build` و `python -m showcase deploy` لإيصال endpoint إلى PythonAnywhere.

### أمثلة مختصرة

```bash
export PORTFOLIO_API_TOKEN='YOUR_PRIVATE_TOKEN'
BASE='https://make1it.pythonanywhere.com/api/v1/projects'
# قراءة أسماء فقط (عشرات التوكنات، مو كل الـ JSON)
curl -H "Authorization: Bearer $PORTFOLIO_API_TOKEN" "$BASE?fields=slug,title"
# قراءة مشروع محدد فقط
curl -H "Authorization: Bearer $PORTFOLIO_API_TOKEN" "$BASE/shajjar?fields=slug,title,desc"
# PATCH: حدّث الوصف فقط؛ تبقى الصور والترتيب وباقي المعلومات
curl -X PATCH "$BASE/shajjar" -H "Authorization: Bearer $PORTFOLIO_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"desc":"منصة مجتمعية لإدارة التشجير والمتابعة"}'
# إنشاء مشروع ثم رفع صورته (لا يظهر المشروع الجديد قبل إضافة صورة)
curl -X POST "$BASE" -H "Authorization: Bearer $PORTFOLIO_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"slug":"my-project","title":"مشروعي","cat":"web","repo":"https://github.com/Thanoon12k/My-Work"}'
curl -X POST "$BASE/my-project/images" -H "Authorization: Bearer $PORTFOLIO_API_TOKEN" \
  -F "image=@screenshot.png"
# حذف مشروع منشأ عبر API فقط؛ المشاريع الأصلية تُخفى بواسطة PATCH {"hidden":true}
curl -X DELETE "$BASE/my-project" -H "Authorization: Bearer $PORTFOLIO_API_TOKEN"
```

الحقول المتاحة للتعديل: `title,en,desc,cat,stack,repo,live_url,featured,hidden`.
أرسل `null` لإلغاء override والعودة لقيمة المشروع الأصلية، و `If-Match` بقيمة
`ETag` من GET لتجنّب الكتابة فوق تحديث متزامن (يرجع 412 عند التعارض).
`GET ?fields=slug,title` يرسل حقلين فقط، و `PATCH` يرجّع تأكيداً مختصراً بدل كامل المشروع.
كل الاستجابات `Cache-Control: no-store`، والمفتاح لا يُقبل في query string.

**ملاحظة:** بيانات API تعدّل العرض الحي مباشرةً بعد نشر إصدار السيرفر، لكن لا تُرسل التغييرات تلقائياً إلى `config.json` أو README في GitHub. المزامنة مع GitHub خطوة منفصلة.
