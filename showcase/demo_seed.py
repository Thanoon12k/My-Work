"""Fill a Django project's own models with believable demo rows, so screenshots of the
real running app show content instead of empty tables. Run with:  manage.py shell < demo_seed.py
Only touches the throwaway SQLite database the showcase creates."""
import datetime, decimal, random

from django.apps import apps
from django.db import models, transaction

random.seed(7)
NAMES = ['أحمد علي', 'سارة محمد', 'يوسف خالد', 'مريم حسن', 'عمر سعد', 'زينب جاسم', 'علي حسين',
         'نور الهدى', 'محمد يونس', 'فاطمة عباس']
WORDS = ['الموصل', 'بغداد', 'أربيل', 'البصرة', 'كركوك', 'النجف']
TEXT = ['متابعة شهرية منتظمة', 'تم الاستلام بنجاح', 'بانتظار المراجعة', 'ملاحظة: يرجى التأكيد',
        'طلب جديد من الزبون']
SKIP_APPS = {'admin', 'auth', 'contenttypes', 'sessions', 'messages', 'staticfiles',
             'authtoken', 'token_blacklist', 'django_celery_beat', 'django_celery_results'}
PER_MODEL = 8


def value(f, i):
    if f.choices:
        return random.choice([c[0] for c in f.flatchoices])
    n = f.name.lower()
    if isinstance(f, models.EmailField):
        return 'user%d@example.com' % i
    if isinstance(f, models.URLField):
        return 'https://example.com/%d' % i
    if isinstance(f, models.SlugField):
        return 'item-%d' % i
    if isinstance(f, (models.CharField, models.TextField)):
        if 'phone' in n or 'mobile' in n or 'هاتف' in n:
            s = '0770%07d' % random.randint(0, 9999999)
        elif 'name' in n or 'title' in n:
            s = NAMES[i % len(NAMES)]
        elif 'address' in n or 'city' in n or 'location' in n:
            s = WORDS[i % len(WORDS)]
        elif 'password' in n:
            s = 'demo-password'
        else:
            s = TEXT[i % len(TEXT)] if isinstance(f, models.TextField) else NAMES[i % len(NAMES)]
        if f.max_length:
            s = s[:f.max_length]
        if f.unique:
            s = (s[:max((f.max_length or 40) - 4, 1)] + ' %d' % i)[:f.max_length or 40]
        return s
    if isinstance(f, models.BooleanField):
        return i % 3 != 0
    if isinstance(f, models.DecimalField):
        top = 10 ** (f.max_digits - f.decimal_places) - 1
        return decimal.Decimal(min(top, random.choice([5000, 12500, 25000, 40000, 75000])))
    if isinstance(f, (models.IntegerField, models.FloatField)):
        if f.unique:
            return 1000 + i
        return random.choice([1, 2, 3, 5, 8, 10, 15, 20, 25, 40])
    if isinstance(f, models.DateTimeField):
        return datetime.datetime.now() - datetime.timedelta(days=i * 3, hours=i)
    if isinstance(f, models.DateField):
        return datetime.date.today() - datetime.timedelta(days=i * 3)
    if isinstance(f, models.TimeField):
        return datetime.time(8 + i % 10, 30)
    if isinstance(f, models.UUIDField):
        import uuid
        return uuid.uuid4()
    if isinstance(f, models.JSONField):
        return {}
    return None


def seed(model, done):
    if model in done or model._meta.abstract or not model._meta.managed or model._meta.proxy:
        return
    done.add(model)
    for f in model._meta.fields:            # parents first
        if f.is_relation and f.related_model and f.related_model is not model:
            seed(f.related_model, done)
    try:
        if model.objects.exists():
            return
    except Exception:
        return
    made = 0
    for i in range(PER_MODEL):
        kw = {}
        ok = True
        for f in model._meta.fields:
            if f.primary_key or f.auto_created or getattr(f, 'auto_now', False) \
                    or getattr(f, 'auto_now_add', False):
                continue
            if f.is_relation:
                rel = f.related_model
                pool = list(rel.objects.all()[:20]) if rel else []
                if pool:
                    kw[f.name] = pool[i % len(pool)]
                elif not f.null:
                    ok = False
                continue
            if isinstance(f, (models.FileField,)):
                continue
            if f.has_default() and not f.choices and not isinstance(f, models.BooleanField):
                continue
            v = value(f, i)
            if v is not None:
                kw[f.name] = v
        if not ok:
            break
        try:
            with transaction.atomic():
                model.objects.create(**kw)
            made += 1
        except Exception:
            continue
    if made:
        print('seeded %s.%s x%d' % (model._meta.app_label, model.__name__, made))


done = set()
for m in apps.get_models():
    if m._meta.app_label not in SKIP_APPS:
        seed(m, done)
