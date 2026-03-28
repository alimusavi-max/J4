# رودمپ بهبود ربات قیمت‌گذاری دیجی‌کالا

این سند برای تبدیل نسخه فعلی به یک ربات قابل اتکا (production-grade) نوشته شده است.

## وضعیت فعلی (Audit خلاصه)
- ✅ دریافت تنوع‌ها (`get_my_variants`) کار می‌کند.
- ⚠️ مسیر کشف کف/سقف قیمت در `discover_price_bounds` خطای محاسباتی داشت (فرمول رُندینگ اشتباه).
- ⚠️ ربات برای ارسال قیمت فقط روی کوکی تکیه می‌کرد و برای بعضی سناریوها هدر CSRF نداشت.
- ⚠️ اگر در حلقه اصلی خطای پیش‌بینی‌نشده رخ می‌داد، امکان توقف چرخه یا رفتار نامشخص وجود داشت.
- ⚠️ مسیر فایل‌های تنظیمات در `main.py` وابسته به cwd بود و می‌توانست در اجرای متفاوت (service/container) اشتباه resolve شود.

## هدف نهایی
رباتی که:
1. **قیمت را درست محاسبه کند** (قانون‌محور + قابل تست).
2. **آپدیت قیمت را قابل اعتماد** بفرستد (retry/backoff/observability).
3. **در برابر تغییرات API دیجی‌کالا مقاوم** باشد.
4. **قابل مانیتور و دیباگ** باشد.

---

## فاز ۱ — تثبیت فوری (۱ تا ۲ روز)

### 1) رفع باگ‌های بحرانی
- اصلاح فرمول محاسبه `test_price` در کشف کف/سقف.
- اضافه‌کردن CSRF header از کوکی برای endpointهای write.
- ایمن‌سازی حلقه `run_bot_loop` با try/except سطح‌بالا و لاگ خطای چرخه.
- یکسان‌سازی مسیر فایل‌های config/settings با مسیر absolute مبتنی بر فایل backend.

### 2) افزودن Checkهای سریع سلامت
- endpoint جدید `GET /api/diagnostics/auth`:
  - تست دسترسی read (variants)
  - تست dry-run write (در صورت امکان با variant sandbox)
  - نمایش اینکه csrf token موجود هست یا نه.

### 3) لاگ قابل اتکا
- استانداردسازی log با شناسه چرخه، variant_id، status_code، latency.

---

## فاز ۲ — قابل اطمینان‌سازی ارسال قیمت (۳ تا ۵ روز)

### 1) ساخت لایه اختصاصی API Client
- یک کلاس `DigikalaSellerClient` بساز:
  - `get_variants_page`
  - `get_competitors`
  - `bulk_update_variants`
- تمام HTTPها فقط از این لایه عبور کنند.

### 2) خط‌مشی Retry حرفه‌ای
- retry فقط برای خطاهای قابل تکرار (429/502/503/timeout).
- backoff نمایی + jitter.
- circuit-breaker ساده: اگر 429 زیاد شد، ربات برای N دقیقه pause شود.

### 3) اعتبارسنجی پاسخ
- parser مرکزی برای پاسخ API:
  - `http_status`
  - `data.errors`
  - `message`
  - map به خطای domain (AUTH_EXPIRED, RATE_LIMITED, VALIDATION_ERROR).

---

## فاز ۳ — بهبود هسته تصمیم‌گیری قیمت (۴ تا ۷ روز)

### 1) موتور Strategy قابل توسعه
- Strategyها را جدا کن:
  - `AggressiveStrategy`
  - `ConservativeStrategy`
  - `FormulaStrategy`
- ورودی استاندارد: `current, competitor, min, max, step, buy_box_price`.

### 2) Guardrailها
- حداقل/حداکثر تغییر قیمت در هر چرخه (مثلا max delta درصدی).
- cooldown per-variant (مثلا هر variant هر X دقیقه بیش از یک بار تغییر نکند).
- جلوگیری از ping-pong با چک تاریخچه کوتاه تغییرات.

### 3) حالت شبیه‌سازی
- `dry_run=true`: فقط تصمیم ثبت شود، ارسال واقعی انجام نشود.
- خروجی مقایسه: `proposed_price`, `reason`, `rule_used`.

---

## فاز ۴ — تست و مانیتورینگ (۳ تا ۵ روز)

### 1) تست
- unit test برای formulaها و strategyها.
- integration test با mock API (responses: 200/401/429/500).
- regression test برای `discover_price_bounds`.

### 2) مانیتورینگ
- متریک‌ها:
  - success rate آپدیت
  - 429 rate
  - median latency
  - buybox win ratio
- dashboard ساده (حتی JSON endpoint برای شروع).

### 3) هشدار
- اگر auth خراب شد یا 429 burst رخ داد، نوتیف (تلگرام/اسلک/وب‌هوک).

---

## فاز ۵ — Production readiness (۲ تا ۴ روز)
- مدیریت secrets (env یا secret manager).
- healthcheck واقعی + readiness/liveness.
- backup/restore تنظیمات.
- runbook عملیاتی (لاگین مجدد، تمدید کوکی، rollback تنظیمات).

---

## KPIهای موفقیت
- نرخ موفقیت آپدیت قیمت: **بالای 95٪**
- نرخ خطای 429: **زیر 5٪ درخواست‌ها**
- زمان بازیابی بعد از اختلال auth: **زیر 15 دقیقه**
- نسبت تصمیم اشتباه/خارج از بازه: **تقریباً صفر**

---

## اولویت پیشنهادی اجرا
1. فاز ۱ (فوری)
2. فاز ۲ (قابلیت اتکا)
3. فاز ۳ (کیفیت تصمیم‌گیری)
4. فاز ۴ (تست/مانیتورینگ)
5. فاز ۵ (عملیاتی)

---

## وضعیت اجرای فعلی (تا فاز ۵)
- ✅ **فاز ۱**: مسیر فایل‌ها پایدار شد، حلقه اصلی fail-safe شد، CSRF header اضافه شد.
- ✅ **فاز ۲**: لایه `DigikalaSellerClient` برای retry/jitter اضافه شد و parsing پاسخ write سخت‌گیرانه‌تر شد.
- ✅ **فاز ۳**: Strategyها به ماژول جدا منتقل شد + guardrailهای `cooldown` و `max_price_change_percent` + `dry_run`.
- ✅ **فاز ۴**: endpointهای `readiness` و `auth diagnostics` برای مانیتورینگ سریع اضافه شد.
- ✅ **فاز ۵**: پشتیبانی از secret توکن با env (`DIGIKALA_AUTH_TOKEN`) و webhook هشدار (`notify_webhook_url`) اضافه شد.
