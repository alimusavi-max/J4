import requests
import json

def apply_new_price(variant_id, new_price, stock, max_per_order, seller_token):
    """
    ارسال قیمت جدید به پنل فروشندگان دیجی‌کالا بر اساس API استخراج شده
    """
    url = "https://seller.digikala.com/api/v2/variants/bulk"
    
    # هدرهای لازم دقیقاً بر اساس فایل لاگ شما تنظیم شده‌اند
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8,fa;q=0.7",
        "content-type": "application/json",
        "origin": "https://seller.digikala.com",
        "referer": "https://seller.digikala.com/pwa/variant-management?page=1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "x-web-optimize-response": "1"
    }
    
    # قرار دادن توکن دسترسی فروشنده در کوکی (استخراج شده از فایل شما)
    cookies = {
        "seller_api_access_token": seller_token
    }
    
    # ساخت پیلود دقیقاً مطابق ساختار درخواستی دیجی‌کالا
    payload = {
        "variants": [
            {
                "variant_id": int(variant_id),
                "shipping_type": "seller",  # ارسال توسط فروشنده
                "seller_lead_time": 1,      # زمان ارسال (می‌توانید داینامیک کنید)
                "selling_price": int(new_price),
                "maximum_per_order": int(max_per_order),
                "seller_stock": int(stock),
                "credit_increase_percentage": 0 # فروش اعتباری (اگر فعال ندارید 0 بگذارید)
            }
        ]
    }
    
    try:
        print(f"🔄 در حال ارسال درخواست تغییر قیمت برای تنوع {variant_id} به {new_price:,} ریال...")
        response = requests.put(url, headers=headers, cookies=cookies, json=payload)
        response.raise_for_status()
        
        data = response.json()
        
        # بررسی وضعیت پاسخ
        if data.get("status") == "ok":
            print("✅ قیمت با موفقیت در دیجی‌کالا آپدیت شد!")
            return True
        else:
            print("⚠️ درخواست ارسال شد اما دیجی‌کالا تایید نکرد. پاسخ سرور:")
            print(data.get("errors", "خطای نامشخص"))
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ خطا در اعمال قیمت جدید: {e}")
        return False

# ==========================================
# تست اسکریپت (با مقادیر فرضی)
# ==========================================
if __name__ == "__main__":
    # توکن خود را باید از کوکی‌های مرورگر یا فایل‌های لاگین خود (manual_cookie_login.py) بگیرید
    MY_SELLER_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzM4NCJ9..." # توکن واقعی را اینجا بگذارید (بدون کلمه seller_api_access_token=)
    
    # دیتای تستی (مثلا خروجی موتور تصمیم‌گیر)
    target_variant = 76498821
    calculated_best_price = 21450000 
    current_stock = 2
    max_order = 2
    
    # برای جلوگیری از تغییر ناخواسته در اکانت شما، خط زیر کامنت شده است.
    # برای تست واقعی، کامنت خط زیر را بردارید و توکن واقعی را قرار دهید.
    
    # apply_new_price(target_variant, calculated_best_price, current_stock, max_order, MY_SELLER_TOKEN)
    print("اسکریپت آماده اتصال به موتور اصلی است.")