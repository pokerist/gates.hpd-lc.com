# Gates - بوابة الدخول الذكية (MVP)

واجهة عربية احترافية للأمن والأدمن مع Manual Debug لاستخراج بيانات بطاقة الرقم القومي.

## المزايا
- واجهة موبايل أولًا للأمن مع كاميرا وفريم مناسب للبطاقة.
- استخراج الاسم الكامل عبر EasyOCR، والرقم القومي عبر Tesseract فقط (في الوضع المحلي).
- دعم Google Document AI كنظام OCR أساسي عند تفعيله.
- لوج تفصيلي في الكونسول لنتائج OCR.
- تخزين صورة البطاقة الشخصية وإظهارها في لوحة الأدمن.
- قاعدة بيانات SQLite لإدارة الدخول والحظر.

## التشغيل على Ubuntu
```
cd id_gate_mvp
bash deploy.sh
```
سيتم التشغيل على `http://<server-ip>:5000`.

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

يمكنك استخدام ملف `.env` بدل التصدير اليدوي. راجع `.env.example`.

## المسارات
- `/` الصفحة الرئيسية
- `/security` واجهة الأمن
- `/admin` لوحة الأدمن
- `/debug` Manual Debug (محمي برمز من الصفحة الرئيسية)

## ملاحظات
- النماذج موجودة داخل `models/`.
- ملفات Tesseract المدربة داخل `tessdata/`.
- قاعدة البيانات: `data/gate.db`.
- صور الأفراد: `data/photos/`.
