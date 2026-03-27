import requests
import json
import time
from datetime import datetime
from pathlib import Path
from utils.manual_cookie_login import ManualCookieManager

BASE_DIR = Path(__file__).resolve().parent.parent
SESSIONS_DIR = BASE_DIR / "panel_sessions"

class DigikalaRepricer:
    def __init__(self, workspace_id, log_callback=None):
        self.workspace_id = workspace_id
        self.log_callback = log_callback
        
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://seller.digikala.com",
            "Referer": "https://seller.digikala.com/pwa/variant-management"
        })
        self._load_cookies()

    def log(self, msg):
        time_str = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{time_str}] {msg}"
        print(full_msg, flush=True)
        if self.log_callback:
            self.log_callback(full_msg)

    def _load_cookies(self):
        cm = ManualCookieManager(SESSIONS_DIR)
        status = cm.check_cookie_validity(self.workspace_id)
        if status['valid']:
            path = cm.get_cookie_path(self.workspace_id)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for c in data.get('cookies', []):
                        if 'name' in c and 'value' in c:
                            self.session.cookies.set(c['name'], c['value'], domain=c.get('domain', ''))
            except Exception as e:
                self.log(f"❌ خطا در خواندن کوکی: {e}")
        else:
            self.log("❌ کوکی یافت نشد. لاگین کنید.")

    def get_my_variants(self, page=1):
        url = f"https://seller.digikala.com/api/v2/variants?page={page}&size=50&sort=product_variant_id&order=desc"
        try:
            response = self.session.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                items = data.get("data", {}).get("items", [])
                total_pages = data.get("data", {}).get("pager", {}).get("total_pages", 1)
                
                variants = []
                for item in items:
                    if item.get("active") and item.get("marketplace_seller_stock", 0) > 0:
                        variants.append({
                            "variant_id": item.get("product_variant_id"),
                            "title": item.get("product_title"),
                            "is_buy_box_winner": item.get("is_buy_box_winner"),
                            "current_price": item.get("price_sale"),
                            "reference_price": item.get("price_list"), 
                            "buy_box_price": item.get("buy_box_price")
                        })
                return {"success": True, "variants": variants, "total_pages": total_pages}
            else:
                return {"success": False, "variants": [], "total_pages": 1}
        except Exception as e:
            self.log(f"خطای شبکه: {e}")
            return {"success": False, "variants": [], "total_pages": 1}

    def get_competitor_price(self, variant_id):
        url = f"https://seller.digikala.com/api/v1/variants/{variant_id}/competitors/"
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                competitors = response.json().get('data', {}).get('competitors', [])
                if not competitors: return None, True 
                
                lowest_comp = float('inf')
                for comp in competitors:
                    if not comp.get('is_me'):
                        price = comp.get('price', float('inf'))
                        if price < lowest_comp: lowest_comp = price
                return lowest_comp, False
            return None, False
        except:
            return None, False

    def update_my_price(self, variant_id, new_price, silent=False):
        # آدرس جدید دیجی‌کالا برای تغییرات گروهی/تکی
        url = "https://seller.digikala.com/api/v2/variants/bulk"
        
        # ساختار جدید Payload بر اساس ریکوئستی که استخراج کردید
        payload = {
            "variants": [
                {
                    "variant_id": int(variant_id),
                    "selling_price": int(new_price)
                }
            ]
        }
        
        try:
            # توجه: متد ارسال از POST به PUT تغییر کرد
            response = self.session.put(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                resp_json = response.json()
                # در نسخه جدید، دیجی‌کالا خطاها را در یک آرایه errors برمی‌گرداند
                errors = resp_json.get("data", {}).get("errors", [])
                
                if not errors:
                    if not silent: self.log(f"✅ [تنوع {variant_id}] قیمت تغییر کرد: {new_price}")
                    return {"success": True, "message": "OK"}
                else:
                    # استخراج متن خطای داخل آرایه
                    error_msg = str(errors)
                    if not silent: self.log(f"⚠️ [تنوع {variant_id}] عدم تایید سایت: {error_msg}")
                    return {"success": False, "message": error_msg}
            else:
                try:
                    error_msg = response.json().get('message', str(response.json()))
                except ValueError:
                    error_msg = f"پاسخ نامعتبر از سرور (کد {response.status_code})."
                
                if not silent: self.log(f"⚠️ [تنوع {variant_id}] خطای سیستم: {error_msg}")
                return {"success": False, "message": str(error_msg)}
                
        except Exception as e:
            if not silent: self.log(f"❌ خطای شبکه/ارتباط: {e}")
            return {"success": False, "message": str(e)}
          
    # نسخه پیشرفته و عمیق کشف بازه (12 مرحله تست برای هر طرف)
    def discover_price_bounds(self, variant_id, reference_price, current_price):
        if not reference_price: reference_price = current_price
        self.log(f"🔍 شروع اسکن مویرگی برای تنوع {variant_id}...")
        
        # 1. جستجوی سقف (Max Price)
        self.log(">> فاز ۱: در حال نفوذ برای پیدا کردن سقف مجاز...")
        max_valid = current_price
        low_pct = 0.0   
        high_pct = 0.8  
        
        for i in range(10): 
            mid = (low_pct + high_pct) / 2
            
            raw_test = reference_price * (1 + mid)
            test_price = int(round(raw_test / 1000.0) * 1000)
            
            self.log(f"سقف {i+1}/10 | تست +{round(mid*100, 2)}% ({test_price} تومان)")
            res = self.update_my_price(variant_id, test_price, silent=False)
            
            # وقفه ۳ ثانیه‌ای برای جلوگیری از بلاک شدن توسط فایروال دیجی‌کالا
            time.sleep(3) 
            
            if res['success']:
                max_valid = test_price
                low_pct = mid 
                self.log("✔️ تایید شد! (بازگردانی فوری)")
                self.update_my_price(variant_id, current_price, silent=True) 
                time.sleep(1) # استراحت کوتاه بعد از بازگردانی
            else:
                high_pct = mid 
                
        # 2. جستجوی کف (Min Price)
        self.log(">> فاز ۲: در حال نفوذ برای پیدا کردن کف مجاز...")
        min_valid = current_price
        low_pct = 0.0   
        high_pct = 0.5  
        
        for i in range(10): 
            mid = (low_pct + high_pct) / 2
            
            raw_test = reference_price * (1 - mid)
            test_price = int(round(raw_test / 1000.0) * 1000)
            
            self.log(f"کف {i+1}/10 | تست -{round(mid*100, 2)}% ({test_price} تومان)")
            res = self.update_my_price(variant_id, test_price, silent=False)
            
            # وقفه ۳ ثانیه‌ای برای جلوگیری از بلاک شدن توسط فایروال دیجی‌کالا
            time.sleep(3)
            
            if res['success']:
                min_valid = test_price
                low_pct = mid 
                self.log("✔️ تایید شد! (بازگردانی فوری)")
                self.update_my_price(variant_id, current_price, silent=True)
                time.sleep(1)
            else:
                high_pct = mid

        self.log(f"🎯 عملیات تمام شد! | کف نهایی: {min_valid} | سقف نهایی: {max_valid}")
        return {"success": True, "min_price": min_valid, "max_price": max_valid}
    
    def evaluate_and_act_all(self, product_configs, step_price=1000):
        self.log("شروع چرخه بررسی...")
        page = 1
        total_pages = 1
        while page <= total_pages:
            res = self.get_my_variants(page)
            if not res['success']: break
            total_pages = res['total_pages']
            
            for item in res['variants']:
                vid = str(item['variant_id'])
                if vid not in product_configs: continue
                    
                conf = product_configs[vid]
                min_p = conf.get('min_price', 0)
                max_p = conf.get('max_price', float('inf'))
                
                if item['is_buy_box_winner']: continue
                    
                comp_price, i_am_buybox = self.get_competitor_price(vid)
                if i_am_buybox or comp_price is None or comp_price == float('inf'): continue

                target_price = comp_price - step_price
                if target_price < min_p:
                    self.log(f"📉 رقیب زیر کف قیمت ماست! ({item['title'][:20]}...)")
                    continue
                elif target_price > max_p:
                    target_price = max_p - step_price

                if target_price != item['current_price']:
                    self.update_my_price(vid, target_price)
                    time.sleep(1)
            page += 1
        self.log("پایان چرخه. منتظر دور بعدی...")