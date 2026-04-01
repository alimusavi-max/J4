import requests
import json

def get_product_buybox_info(product_id):
    """
    دریافت اطلاعات لحظه‌ای فروشندگان و بای‌باکس برای یک محصول از API عمومی دیجی‌کالا
    """
    url = f"https://api.digikala.com/v2/product/{product_id}/"
    
    # استفاده از هدرهای استاندارد برای جلوگیری از بلاک شدن درخواست
    headers = {
        "accept": "application/json, text/plain, */*",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "x-web-client": "desktop"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status() # بررسی خطاهای HTTP
        data = response.json()
        
        # استخراج لیست تنوع‌ها (فروشندگان مختلف برای این کالا)
        variants = data.get("data", {}).get("product", {}).get("variants", [])
        
        if not variants:
            print(f"⚠️ هیچ تنوعی برای محصول DKP-{product_id} یافت نشد (شاید ناموجود است).")
            return None
        
        print(f"\n📊 در حال تحلیل رقبا برای محصول DKP-{product_id}:")
        print("-" * 70)
        
        extracted_data = []
        
        for variant in variants:
            # 1. استخراج DKPC (شناسه یکتای تنوع)
            dkpc = variant.get("id") 
            
            # 2. استخراج اطلاعات فروشنده
            seller_info = variant.get("seller", {})
            seller_name = seller_info.get("title", "نامشخص")
            seller_id = seller_info.get("id", 0)
            seller_rate = seller_info.get("rating", {}).get("total_rate", 0)
            
            # 3. استخراج قیمت و وضعیت بای‌باکس
            price = variant.get("price", {}).get("selling_price", 0)
            
            # دیجی‌کالا برنده بای‌باکس را با فلگ is_winner یا قرار دادن در ایندکس صفر مشخص می‌کند
            # برای اطمینان بیشتر فلگ‌ها را چک می‌کنیم
            is_winner = variant.get("is_winner", False)
            if "buy_box_winner" in variant:
                is_winner = variant.get("buy_box_winner")
                
            # ذخیره در یک دیکشنری تمیز برای استفاده در موتور قیمت‌گذاری
            variant_data = {
                "dkpc": dkpc,
                "seller_name": seller_name,
                "seller_id": seller_id,
                "seller_rate": seller_rate,
                "price": price,
                "is_winner": is_winner
            }
            extracted_data.append(variant_data)
            
            # چاپ خروجی برای تست
            status = "🏆 [برنده بای‌باکس]" if is_winner else "   [رقیب عادی]"
            print(f"{status} قیمت: {price:,} ریال | DKPC: {dkpc} | فروشنده: {seller_name} (امتیاز: {seller_rate})")
            
        print("-" * 70)
        return extracted_data

    except requests.exceptions.RequestException as e:
        print(f"❌ خطا در ارتباط با سرور دیجی‌کالا: {e}")
        return None

# ==========================================
# تست کد با شناسه کالای VGR V-188 (از لاگ‌های شما)
# ==========================================
if __name__ == "__main__":
    test_product_id = 4874481
    scout_results = get_product_buybox_info(test_product_id)
    
    # اینجا می‌بینیم که چطور می‌توانیم DKPC خودمان و رقیب را اتوماتیک پیدا کنیم
    if scout_results:
        my_seller_id = 1184130 # شناسه فروشگاه دریای آرام ممتاز
        
        my_dkpc = None
        winner_price = None
        
        for item in scout_results:
            if item["seller_id"] == my_seller_id:
                my_dkpc = item["dkpc"]
            if item["is_winner"]:
                winner_price = item["price"]
                
        print(f"\n✅ خروجی برای مرحله بعد (موتور قیمت‌گذاری):")
        print(f"- شناسه DKPC فروشگاه شما برای این کالا به صورت خودکار پیدا شد: {my_dkpc}")
        print(f"- قیمت فعلی برنده بای باکس: {winner_price:,} ریال")