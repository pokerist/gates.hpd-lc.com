# Authentication Guide

## الهدف
تأمين نقاط النهاية الخاصة بتطبيق الأمن (الموبايل) عبر مفتاح API بسيط.

## المتطلبات
حدد متغير البيئة التالي على السيرفر:
```
SECURITY_API_KEY=your-mobile-app-key
```

## طريقة الإرسال
أي طلب لتطبيق الأمن لازم يحتوي على الهيدر:
```
X-API-Key: <SECURITY_API_KEY>
```

## نقاط النهاية المحمية
رفع صورة Base64:
```
POST /api/v1/security/scan-base64
Content-Type: application/json
```

Body:
```
{
  "image_base64": "<base64 or data:image/jpeg;base64,...>"
}
```

## أكواد الاستجابة
- `200` نجاح
- `401` مفتاح غير صحيح
- `422` خطأ في التعرف على الرقم القومي/البيانات
- `400` بيانات صورة غير صالحة

## ملاحظات
- في حالة Base64 يمكن إرسال Data URL كامل أو محتوى Base64 فقط.
