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
