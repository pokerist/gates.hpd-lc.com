# Authentication (External Security API)

هذا المستند خاص بمصادقة تطبيق الأمن (الموبايل) عند استدعاء الـ API الخارجي.

## المفتاح
قم بتعيين المفتاح في السيرفر:
```
SECURITY_API_KEY=your-mobile-app-key
```

## طريقة الإرسال
كل طلب يجب أن يحتوي على الهيدر:
```
X-API-Key: <SECURITY_API_KEY>
```

## Endpoint المستخدم حالياً
```
POST /api/v1/security/scan-base64
Content-Type: application/json
```

Body:
```json
{
  "image_base64": "<base64 أو data:image/jpeg;base64,...>"
}
```

## الردود المتوقعة
**نجاح (مسموح):**
```json
{
  "status": "allowed",
  "message": "مسموح بالدخول",
  "is_new": true
}
```

**محظور:**
```json
{
  "status": "blocked",
  "message": "هذا الشخص محظور من الدخول",
  "reason": "سبب الحظر",
  "is_new": false
}
```

**خطأ:**
```json
{
  "status": "error",
  "message": "فشل إيجاد بطاقة شخصية في الصورة. برجاء التأكد من التصوير بشكل صحيح"
}
```

## أكواد الاستجابة
- `200` نجاح (`allowed` أو `blocked`).
- `401` مفتاح API غير صحيح.
- `422` خطأ في التعرف أو في البطاقة.
- `429` تجاوز معدل الطلبات.
- `400` بيانات صورة غير صالحة.
