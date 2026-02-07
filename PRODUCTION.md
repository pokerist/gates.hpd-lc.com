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
- `/api/v1/security/scan` محمي بـ `X-API-Key`

## ملاحظات مهمة
- لا يوجد migrations في النظام.
- قم بمراجعة إعدادات الأمان (API key) بانتظام.
