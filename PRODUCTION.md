# Production Checklist

## المتطلبات
- Ubuntu + Python 3.12
- PostgreSQL جاهز (أو Docker)
- إعدادات البيئة في `.env`

## إعداد قاعدة البيانات
### خيار 1: PostgreSQL خارجي
```
DATABASE_URL=postgresql://user:pass@host:5432/gates_db
```

### خيار 2: Docker
```
START_POSTGRES=1
POSTGRES_DB=gates_db
POSTGRES_USER=gates
POSTGRES_PASSWORD=gatespass
```

## تشغيل السيرفر
```
bash deploy.sh production
```

## تشغيل الخلفية (Redis/RQ)
لتسريع استجابة تطبيق الموبايل، شغّل Redis ثم عامل RQ:
```
START_REDIS=1
```
ثم في جلسة أخرى:
```
export REDIS_URL=redis://localhost:6379/0
export RQ_QUEUE=gates
rq worker gates
```
في وضع production يتم تشغيل العامل تلقائيًا عند تشغيل `deploy.sh` (وتسجيل لوجاته في `data/logs/rq.log`).

## Rate Limiting
الإعدادات في `.env`:
```
RATE_LIMIT_ENABLED=1
RATE_LIMIT_WINDOW_SEC=60
RATE_LIMIT_MAX=20
TRUST_PROXY=1
```

## نقاط التحقق
- `/api/health` يرجع `ok`
- `/admin` يعمل بدون أخطاء
- `/api/v1/security/scan-base64` محمي بـ `X-API-Key`

## ملاحظات مهمة
- لا يوجد migrations في النظام.
- قم بمراجعة إعدادات الأمان (API key) بانتظام.
