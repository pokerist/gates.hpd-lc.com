# تشغيل Production (Runbook)

هذا المستند يشرح التشغيل الإنتاجي الفعلي كما هو مطبق حالياً.

## المتطلبات
- Ubuntu 22/24
- Python 3.12
- Docker (اختياري لتشغيل PostgreSQL محلياً)
- Redis (اختياري لكنه موصى به لتشغيل الـ RQ Worker)

## 1) تجهيز البيئة
عند أول تشغيل، يقوم `deploy.sh` بإنشاء `.env` تلقائياً من `.env.example`.
قم بتعديل القيم الأساسية قبل التشغيل:
- `SECURITY_API_KEY`
- `ADMIN_USERNAME` و `ADMIN_PASSWORD`
- `SESSION_SECRET`
- إعدادات Document AI (إن كنت ستستخدمه)

## 2) تشغيل الإنتاج
```
bash deploy.sh production
```
ماذا يفعل السكربت:
- تثبيت المتطلبات وإنشاء venv.
- تجهيز مجلدات البيانات.
- تشغيل PostgreSQL (إن كان `START_POSTGRES=1` و Docker متوفر).
- تشغيل Redis و RQ Worker (إن كان مفعلاً).
- تشغيل التطبيق على المنفذ `5000`.

## 3) تشغيل دائم بعد إعادة التشغيل
إذا كان `USE_SYSTEMD=1` و `systemctl` متوفر:
- سيتم إنشاء خدمات systemd وتشغيلها تلقائياً:
- `gates-app`
- `gates-rq`

أوامر مفيدة:
```
systemctl status gates-app
systemctl status gates-rq
systemctl restart gates-app gates-rq
```

## 4) قاعدة البيانات
### PostgreSQL خارجي
اضبط:
```
DATABASE_URL=postgresql://user:pass@host:5432/gates_db
```

### PostgreSQL عبر Docker
اضبط:
```
START_POSTGRES=1
POSTGRES_DB=gates_db
POSTGRES_USER=gates
POSTGRES_PASSWORD=gatespass
POSTGRES_PORT=5432
```
ملاحظة: إذا كان المنفذ `5432` مستخدماً، سيحوّل السكربت تلقائياً إلى `5433`.

## 5) Redis و RQ
- يتم تشغيلهما تلقائياً في production عند تفعيل `START_REDIS=1`.
- اللوجات في `data/logs/rq.log`.

## 6) فحوصات سريعة
- Health Check: `GET /api/health`
- الدخول إلى لوحة الأدمن: `GET /login`
- اختبار API الخارجي عبر `/api/v1/security/scan-base64`

## 7) السجلات (Logs)
- `data/logs/access.log`
- `data/logs/error.log`
- `data/logs/rq.log`

## 8) النسخ الاحتياطي
- قاعدة البيانات: `pg_dump` بشكل دوري.
- الصور: انسخ مجلد `data/photos` و `data/cards`.

## 9) Rate Limiting
القيم من `.env`:
```
RATE_LIMIT_ENABLED=1
RATE_LIMIT_WINDOW_SEC=60
RATE_LIMIT_MAX=20
TRUST_PROXY=1
```

## ملاحظات مهمة
- النظام لا يستخدم migrations، الجداول تُنشأ تلقائياً.
- يفضل تشغيله خلف Reverse Proxy مع HTTPS.
