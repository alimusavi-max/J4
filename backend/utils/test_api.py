import requests
import time
import random

def update_variant_price_bulk(variant_id, price, stock, lead_time, headers):
    """
    تابع ارسال درخواست آپدیت قیمت به دیجی‌کالا با مدیریت خطا و محدودیت سرعت
    """
    url = "https://seller.digikala.com/api/v2/variants/bulk"
    
    # ساختار دقیق پیلود همراه با seller_lead_time
    payload = {
        "variants": [
            {
                "variant_id": variant_id,
                "shipping_type": "seller",
                "seller_lead_time": lead_time,
                "selling_price": price,
                "seller_stock": stock,
                "maximum_per_order": 4
            }
        ]
    }

    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            # وقفه تصادفی برای رفتار انسانی‌تر و جلوگیری از حساس شدن فایروال (بین ۳ تا ۶ ثانیه)
            time.sleep(random.uniform(3, 6))
            
            print(f"🔄 در حال ارسال درخواست برای تنوع {variant_id} (تلاش {attempt + 1})...")
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            
            # بررسی ارور 429 (Too Many Requests)
            if response.status_code == 429:
                print(f"⚠️ خطای 429: محدودیت سرعت اعمال شد. 10 ثانیه توقف...")
                time.sleep(10)
                continue 
                
            # بررسی موفقیت آمیز بودن آپدیت
            if response.status_code == 200:
                print(f"✅ آپدیت موفق! قیمت جدید: {price} ثبت شد.")
                return True
                
            # مدیریت سایر خطاهای سمت سرور (مثل 400 که نشون‌دهنده دیتای اشتباهه)
            print(f"❌ خطای سایت (کد {response.status_code}): {response.text}")
            break 
            
        except requests.exceptions.RequestException as e:
            # مدیریت قطعی‌های لحظه‌ای پکت‌ها یا خطای DNS
            print(f"❌ خطای شبکه/ارتباط: {e}")
            print("⏳ 5 ثانیه صبر و تلاش مجدد...")
            time.sleep(5)
            
    print(f"⚠️ عملیات برای تنوع {variant_id} به پایان رسید (ناموفق).")
    return False

# ==========================================
# بخش اجرایی اسکریپت (مخصوص تست)
# ==========================================
if __name__ == "__main__":
    
    # ۱. توکن اختصاصی پنل خودت رو اینجا جایگزین کن
    MY_HEADERS = {
        "Authorization": "YOUR_TOKEN_HERE", # کلمه Bearer یا ساختار توکنت رو رعایت کن
        "Content-Type": "application/json"
    }

    # ۲. دیتای تستی که فرستاده بودی
    TEST_VARIANT = 75547353
    TEST_PRICE = 27000000
    TEST_STOCK = 79
    TEST_LEAD_TIME = 2

    print("🚀 شروع تست اسکریپت آپدیت...")
    
    # فراخوانی تابع
    success = update_variant_price_bulk(
        variant_id=TEST_VARIANT, 
        price=TEST_PRICE, 
        stock=TEST_STOCK, 
        lead_time=TEST_LEAD_TIME, 
        headers=MY_HEADERS
    )

    if success:
        print("🎉 تست با موفقیت پاس شد. حالا می‌تونی این تابع رو ببری تو حلقه اصلی رباتت.")
    else:
        print("بررسی کن ببین ارور جدیدی توی لاگ بالا داده یا نه.")