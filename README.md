# Gates Hyde Park — نظام إدارة الدخول

نظام إدارة دخول يعتمد على مطابقة الوجه محلياً مع OCR للبطاقة القومية المصرية. الواجهة الأساسية هي لوحة الأدمن والـ Manual Debug، أما “الأمن” فيستخدم تطبيق موبايل يتواصل مع API خارجي على المنفذ `5000`.

## ماذا يعمل النظام الآن
- مطابقة وجه محلية (InsightFace / ArcFace) للرد السريع على أفراد الأمن.
- OCR أساسي عبر Google Document AI لاستخراج الاسم والرقم القومي.
- Tesseract يستخدم فقط كـ fallback لاستخراج الرقم القومي عندما يفشل Document AI.
- تسجيل الأشخاص الجدد يتم فورياً مع رد سريع، ثم يُستكمل OCR في الخلفية عبر Redis/RQ.
- لوحة أدمن لإدارة الأشخاص (بحث، حظر/إلغاء حظر، تعديل البيانات، حذف).
- Manual Debug لرفع صورة وعرض خطوات المعالجة، الصور، والـ timings.
- تخزين صورة الوجه وصورة البطاقة الأصلية لكل سجل.

## تدفق المعالجة (Flow)
1. تطبيق الموبايل يرسل صورة البطاقة كـ Base64 إلى `/api/v1/security/scan-base64`.
2. السيرفر يفك الترميز ويكتشف البطاقة ويستخرج صورة الوجه.
3. يتم عمل Face Match محلياً.
4. في حالة وجود تطابق:
- يتم الرد فوراً بحالة `allowed` أو `blocked`.
- يتم تحديث الزيارات وتخزين أحدث صورة وجه/بطاقة.
5. في حالة عدم وجود تطابق:
- يتم إنشاء سجل مؤقت فوراً مع صورة الوجه والبطاقة.
- يتم الرد فوراً بحالة `allowed` مع `is_new=true`.
- يتم تشغيل Job في الخلفية لإكمال OCR وربط البيانات.
6. Job الخلفية يستخدم Document AI، ولو فشل الرقم القومي فقط يتم استخدام Tesseract للرقم القومي.
7. لو فشل OCR بالكامل، يظل السجل موجودًا مع صورة الوجه والبطاقة ويُعدل يدوياً من الأدمن.

## واجهات الويب
- `/login` تسجيل الدخول.
- `/admin` لوحة الأدمن (تتطلب تسجيل الدخول).
- `/debug` Manual Debug + الإعدادات (تتطلب تسجيل الدخول ثم PIN).
- `/security` و `/settings` تُرجع 404 ولا تستخدم حالياً.

## Manual Debug
- يتطلب تسجيل دخول أدمن ثم إدخال `DEBUG_PIN`.
- يعرض:
- صورة البطاقة المرسلة ونسخة Document AI المصغرة.
- صورة الوجه المستخرجة.
- الحقول المكتشفة والـ timings.
- مخرجات Document AI و Tesseract.

## REST API (تطبيق الأمن)
**Endpoint**
- `POST /api/v1/security/scan-base64`

**Headers**
- `X-API-Key: <SECURITY_API_KEY>`

**Body**
```json
{
  "image_base64": "<base64 أو data:image/jpeg;base64,...>"
}
```

**Response (نجاح)**
```json
{
  "status": "allowed",
  "message": "مسموح بالدخول",
  "is_new": true
}
```

**Response (محظور)**
```json
{
  "status": "blocked",
  "message": "هذا الشخص محظور من الدخول",
  "reason": "سبب الحظر",
  "is_new": false
}
```

**Response (خطأ)**
```json
{
  "status": "error",
  "message": "فشل إيجاد بطاقة شخصية في الصورة. برجاء التأكد من التصوير بشكل صحيح"
}
```

**أكواد الاستجابة**
- `200` نجاح (`allowed` أو `blocked`).
- `401` مفتاح API غير صحيح.
- `422` خطأ في التعرف أو في البطاقة.
- `429` تجاوز معدل الطلبات.
- `400` صورة غير صالحة.

## إعداد Google Document AI
لتفعيل OCR عبر Document AI:
1) ضع ملف service account وأشر إليه:
```
GOOGLE_APPLICATION_CREDENTIALS=/opt/gates/keys/docai-key.json
```
2) اضبط المعرفات:
```
DOC_AI_PROJECT_ID=hydepark-gate-keeper
DOC_AI_PROJECT_NUMBER=82843412741
DOC_AI_LOCATION=us
DOC_AI_PROCESSOR_ID=4a6c7685906ef3c9
```
3) أنواع الـ Entities (لو تغيّرت في التدريب):
```
DOC_AI_NAME_TYPES=fullName
DOC_AI_NID_TYPES=NationalID
```
4) جودة الصورة المرسلة لـ Document AI:
```
DOC_AI_MAX_DIM=1600
DOC_AI_JPEG_QUALITY=85
```

## إعدادات من صفحة Debug
هذه الإعدادات تحفظ في قاعدة البيانات وتؤثر مباشرة:
- `docai_grayscale` تحويل الصورة إلى أبيض وأسود قبل الإرسال.
- `docai_max_dim` أقصى بعد للصورة قبل الإرسال.
- `docai_jpeg_quality` جودة JPEG للصور المرسلة.
- `face_match_enabled` تفعيل/تعطيل مطابقة الوجه.
- `face_match_threshold` عتبة التشابه.

## التشغيل (Development)
```
cd id_gate_mvp
bash deploy.sh dev
```
السيرفر يعمل على `http://<server-ip>:5000`.

## التشغيل (Production)
```
bash deploy.sh production
```
- يستخدم Gunicorn + Uvicorn workers.
- اللوجات داخل `data/logs/`.
- يشغّل Redis و RQ تلقائياً إن كان مفعلًا.
- لو النظام يدعم systemd سيتم إنشاء خدمات دائمة تلقائياً.

## الخدمات في Production (systemd)
في حال `USE_SYSTEMD=1` سيتم إنشاء خدمات:
- `gates-app`
- `gates-rq`

أوامر مفيدة:
```
systemctl status gates-app
systemctl status gates-rq
systemctl restart gates-app gates-rq
```

## قاعدة البيانات
- في الإنتاج يتم استخدام PostgreSQL تلقائياً.
- في التطوير يتم استخدام SQLite افتراضياً.
- يمكن إجبار النوع عبر `DB_BACKEND=postgres` أو `DB_BACKEND=sqlite`.
- PostgreSQL يُدار داخل Schema مستقل عبر `PG_SCHEMA` (افتراضي `gates`).

## المسارات والملفات
- `data/photos/` صور الوجوه.
- `data/cards/` صور البطاقة الأصلية والمقصوصة.
- `data/raw/` رفع خام مؤقت (يُحذف بعد المعالجة).
- `data/debug/` صور الـ Debug.
- `data/logs/` لوجات السيرفر و RQ.

## متغيرات البيئة المهمة
- `ADMIN_USERNAME`, `ADMIN_PASSWORD` بيانات الأدمن.
- `DEBUG_PIN` رقم PIN للـ Debug.
- `SESSION_SECRET` لتأمين الجلسات.
- `SECURITY_API_KEY` مفتاح API لتطبيق الأمن.
- `CARD_AUTO_ROTATE=0` تعطيل تدوير الصورة تلقائياً.
- `REDIS_URL`, `RQ_QUEUE`, `RQ_JOB_TIMEOUT` لتشغيل الخلفية.
- `START_REDIS=1` لتثبيت وتشغيل Redis عبر `deploy.sh`.
- `USE_SYSTEMD=1` لتشغيل الخدمات تلقائياً بعد إعادة التشغيل.
- `APP_ENV=production` لتفعيل PostgreSQL تلقائياً.

## أمان وتشغيل موثوق
- لا تشارك `.env` أو مفاتيح الخدمة.
- فعّل HTTPS عبر Nginx أو أي Reverse Proxy خارجي.
- راقب `data/logs/error.log` لأي أخطاء.
- نفّذ نسخ احتياطي دوري لقاعدة البيانات والصور.
