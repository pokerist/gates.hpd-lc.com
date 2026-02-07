# Gates - بوابة الدخول الذكية (MVP)

واجهة عربية احترافية للأمن والأدمن مع Manual Debug لاستخراج بيانات بطاقة الرقم القومي.

## المزايا
- واجهة موبايل أولًا للأمن مع كاميرا وفريم مناسب للبطاقة.
- استخراج الرقم القومي عبر Tesseract محليًا (Fallback).
- دعم Google Document AI كنظام OCR أساسي للاسم والرقم القومي عند تفعيله.
- مطابقة وجه محلية (InsightFace / ArcFace) لتقليل تكلفة Document AI.
- لوج تفصيلي في الكونسول لنتائج OCR.
- تخزين صورة البطاقة الشخصية وإظهارها في لوحة الأدمن.
- معالجة خلفية عبر Redis/RQ لتسريع الاستجابة عند تسجيل أشخاص جدد.
- دعم SQLite و PostgreSQL لإدارة الدخول والحظر.

## التشغيل على Ubuntu
```
cd id_gate_mvp
bash deploy.sh dev
```
سيتم التشغيل على `http://<server-ip>:5000`.

## تشغيل Production
```
bash deploy.sh production
```
سيتم تشغيل Gunicorn مع Uvicorn workers وتسجيل اللوجات داخل `data/logs/`.
راجع `PRODUCTION.md` لتجهيز الإنتاج بالكامل.

## تشغيل Worker (RQ)
معالجة تسجيل الأشخاص الجدد تتم في الخلفية لتسريع رد تطبيق الموبايل.

1. تأكد من تشغيل Redis أو فعّل:
```
START_REDIS=1
```
2. شغّل عامل RQ (في نافذة أخرى):
```
export REDIS_URL=redis://localhost:6379/0
export RQ_QUEUE=gates
rq worker gates
```
بدون Redis سيعمل النظام لكن التسجيل الخلفي سيتم داخل نفس السيرفر وقد يبطئ الاستجابة.

## قاعدة البيانات
### PostgreSQL (Production)
حدد متغير:
```
export DATABASE_URL=postgresql://user:pass@host:5432/gates_db
```
وعند التشغيل بـ:
```
bash deploy.sh production
```
سيتم استخدام PostgreSQL مباشرة.

### استخدام PostgreSQL في Development (اختياري)
```
export DB_BACKEND=postgres
export DATABASE_URL=postgresql://user:pass@host:5432/gates_db
bash deploy.sh dev
```

أو يمكن تشغيل PostgreSQL عبر Docker:
```
export START_POSTGRES=1
export POSTGRES_DB=gates_db
export POSTGRES_USER=gates
export POSTGRES_PASSWORD=gatespass
bash deploy.sh production
```
سيتم تشغيل حاوية `gates-postgres` وربطها تلقائيًا.

### SQLite (Development فقط)
```
export APP_ENV=development
bash deploy.sh dev
```
يتم استخدام `data/gate_dev.db` تلقائيًا.

## إعداد Google Document AI (اختياري)
لتفعيل Document AI بدل الـ OCR المحلي:

1) ثبّت Service Account وضبط الاعتماد:
```
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

2) اضبط المتغيرات التالية:
```
export DOC_AI_PROJECT_ID=hydepark-gate-keeper
export DOC_AI_PROJECT_NUMBER=82843412741
export DOC_AI_LOCATION=us
export DOC_AI_PROCESSOR_ID=4a6c7685906ef3c9
```

3) (اختياري) لو أسماء الـ entities مختلفة عن الافتراض:
```
export DOC_AI_NAME_TYPES=full_name,name,arabic_name
export DOC_AI_NID_TYPES=national_id,nid,id_number
```

4) (اختياري) لتسريع الاستجابة بتقليل حجم الصورة المرسلة:
```
export DOC_AI_MAX_DIM=1600
export DOC_AI_JPEG_QUALITY=85
```

## مطابقة الوجه
- فعّلها من صفحة الإعدادات.
- قيمة التشابه الافتراضية: `0.35` (Cosine Similarity).

## إعدادات الأداء
- `DOC_AI_MAX_DIM` و `DOC_AI_JPEG_QUALITY` يمكن ضبطهما من صفحة الإعدادات مباشرة.

يمكنك استخدام ملف `.env` بدل التصدير اليدوي. راجع `.env.example`.

## المسارات
- `/login` تسجيل الدخول
- `/admin` لوحة الأدمن (بعد تسجيل الدخول)
- `/debug` Manual Debug + الإعدادات (يتطلب PIN بعد تسجيل الدخول)

## REST API للأمن (تطبيق الموبايل)
Endpoint:
- `POST /api/v1/security/scan-base64`

Headers:
- `X-API-Key: <SECURITY_API_KEY>`

Body (application/json):
```
{
  "image_base64": "<base64 or data:image/jpeg;base64,...>"
}
```

Response (مختصر لتطبيق الموبايل):
```
{
  "status": "allowed|blocked|error",
  "message": "مسموح بالدخول",
  "is_new": true,
  "reason": "سبب الحظر (لو blocked)"
}
```

ملاحظة: الرد سريع (Face Match فقط)، وأي تسجيل جديد يتم استكماله في الخلفية.

ملاحظة: لاستخدامه، عرّف المتغير `SECURITY_API_KEY` في السيرفر.
راجع `AUTH.md` للتفاصيل الكاملة.

## الدخول للويب
- `/login` لتسجيل دخول الأدمن.
- بيانات الدخول تُقرأ من `.env` عبر `ADMIN_USERNAME` و`ADMIN_PASSWORD`.
- صفحة الـDebug تتطلب إدخال PIN (`DEBUG_PIN`) بعد تسجيل الدخول.

## ملاحظات
- النماذج موجودة داخل `models/`.
- ملفات Tesseract المدربة داخل `tessdata/`.
- قاعدة البيانات: `data/gate.db`.
- صور الأفراد: `data/photos/`.
- صور البطاقات: `data/cards/`.

## متغيرات البيئة المهمة
- `ADMIN_USERNAME` و `ADMIN_PASSWORD` لتسجيل دخول الأدمن.
- `DEBUG_PIN` لفتح صفحة الـDebug بعد تسجيل الدخول.
- `SESSION_SECRET` لتأمين جلسات الدخول.
- `FACE_MAX_DIM` أقصى حجم لإدخال الوجه (افتراضي 640).
- `FACE_DET_SIZE` حجم كاشف الوجوه (افتراضي 640).
- `FACE_MIN_SCORE` أقل درجة قبول لاكتشاف الوجه (افتراضي 0.5).
- `FACE_MAX_CANDIDATES` أقصى عدد مرشحين للمطابقة (افتراضي 50).
- `REDIS_URL` عنوان Redis (مطلوب لـ RQ).
- `RQ_QUEUE` اسم الـ Queue (افتراضي gates).
- `RQ_JOB_TIMEOUT` أقصى وقت للوظيفة بالثواني.
- `START_REDIS` لتثبيت وتشغيل Redis تلقائياً عبر `deploy.sh`.
