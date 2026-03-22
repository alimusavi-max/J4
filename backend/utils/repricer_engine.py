import requests
import json
import time
from datetime import datetime
from pathlib import Path

# ایمپورت کردن مدیریت کوکی‌های خودت
from manual_cookie_login import ManualCookieManager

BASE_DIR = Path(__file__).resolve().parent.parent
SESSIONS_DIR = BASE_DIR / "panel_sessions"

class DigikalaRepricer:
    def __init__(self, workspace_id, variant_id, min_price, max_price, step_price=1000):
        self.workspace_id = workspace_id
        self.variant_id = variant_id # شناسه تنوع کالا (نه DKPC اصلی، بلکه کد تنوع فروشنده)
        self.min_price = min_price
        self.max_price = max_price
        self.step_price = step_price # پله‌های کاهش قیمت (مثلا ۱۰۰۰ تومان)
        
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://seller.digikala.com",
            "Referer": "https://seller.digikala.com/"
        })
        self._load_cookies()

    def log(self, msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [🤖 Repricer] {msg}", flush=True)

    def _load_cookies(self):
        """لود کردن کوکی‌های اکانت از فایل‌های موجود در سیستم فعلی"""
        cm = ManualCookieManager(SESSIONS_DIR)
        status = cm.check_cookie_validity(self.workspace_id)
        
        if status['valid']:
            path = cm.get_cookie_path(self.workspace_id)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    cookies = data.get('cookies', [])
                    for c in cookies:
                        if 'name' in c and 'value' in c:
                            self.session.cookies.set(c['name'], c['value'], domain=c.get('domain', ''))
                self.log("✅ کوکی‌ها با موفقیت در سشن ربات لود شدند.")
            except Exception as e:
                self.log(f"❌ خطا در خواندن فایل کوکی: {e}")
        else:
            self.log("❌ کوکی معتبری یافت نشد. لطفاً ابتدا در پنل اصلی لاگین کنید.")

    def get_competitor_price(self):
        """
        دریافت قیمت بای‌باکس و اطلاعات رقبا.
        نکته: این API ممکنه در دیجی‌کالا تغییر کنه. اگر کار نکرد، از Network مرورگر آدرس دقیق رو جایگزین کن.
        """
        # آدرس API برای دریافت اطلاعات تنوع و قیمت‌های سایر فروشندگان
        url = f"https://seller.digikala.com/api/v1/variants/{self.variant_id}/competitors/"
        
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # این بخش بستگی به ساختار دقیق JSON دیجی‌کالا دارد. 
                # فرض میکنیم ارزان‌ترین قیمت رقیب را از لیست برمی‌دارد.
                competitors = data.get('data', {}).get('competitors', [])
                
                if not competitors:
                    self.log("تنوع رقیبی یافت نشد. شما در بای‌باکس هستید.")
                    return None, True # قیمت رقیب نداریم، بای باکس دست ماست

                # پیدا کردن ارزان ترین قیمت رقیب (صرف نظر از خودمان)
                lowest_competitor_price = float('inf')
                for comp in competitors:
                    if not comp.get('is_me'): # اگر خودمان نیستیم
                        price = comp.get('price', float('inf'))
                        if price < lowest_competitor_price:
                            lowest_competitor_price = price
                            
                return lowest_competitor_price, False
            else:
                self.log(f"⚠️ خطا در دریافت قیمت رقبا. کد وضعیت: {response.status_code}")
                return None, False
        except Exception as e:
            self.log(f"❌ خطای شبکه در دریافت قیمت: {e}")
            return None, False

    def update_my_price(self, new_price):
        """ارسال درخواست تغییر قیمت به دیجی‌کالا"""
        url = "https://seller.digikala.com/api/v1/variants/price/"
        
        payload = {
            "variants": [
                {
                    "id": self.variant_id,
                    "price": int(new_price)
                }
            ]
        }
        
        try:
            response = self.session.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                self.log(f"✅ قیمت با موفقیت به {new_price} تومان تغییر کرد!")
                return True
            else:
                self.log(f"❌ خطا در تغییر قیمت. پاسخ سرور: {response.text}")
                return False
        except Exception as e:
            self.log(f"❌ خطای شبکه در هنگام تغییر قیمت: {e}")
            return False

    def evaluate_and_act(self):
        """هسته اصلی منطق تله سقف و کف"""
        self.log("در حال بررسی قیمت‌ها...")
        comp_price, i_am_buybox = self.get_competitor_price()

        if i_am_buybox:
            self.log("بای‌باکس دست شماست. نیازی به تغییر نیست.")
            return

        if comp_price is None or comp_price == float('inf'):
            self.log("اطلاعات رقیب پردازش نشد.")
            return

        self.log(f"ارزان‌ترین رقیب: {comp_price} | کف ما: {self.min_price} | سقف ما: {self.max_price}")

        # منطق استراتژی
        if comp_price >= self.max_price:
            # رقیب پریده روی سقف یا بالاتر! ما بای باکس رو با سود عالی می‌گیریم
            target_price = self.max_price - self.step_price
            self.log(f"🎯 رقیب به سقف رسید! تنظیم روی قیمت هدف: {target_price}")
            self.update_my_price(target_price)
            
        elif comp_price <= self.min_price:
            # رقیب به کف چسبیده است. ما هیچ کاری نمی‌کنیم تا او بدون سود بفروشد
            self.log("📉 رقیب در کف قیمت است. او را رها می‌کنیم تا سودش صفر بماند.")
            
        elif self.min_price < comp_price < self.max_price:
            # رقیب بین کف و سقف است. ما ۱۰۰۰ تومن می‌آییم زیر قیمت او
            target_price = comp_price - self.step_price
            if target_price < self.min_price:
                target_price = self.min_price # از کف خودمان پایین‌تر نمی‌رویم
                
            self.log(f"⚔️ رقابت در جریان است. تغییر قیمت به: {target_price}")
            self.update_my_price(target_price)

# =====================================================================
# بخش تست مستقل
# =====================================================================
if __name__ == "__main__":
    import shutil
    
    # 1. کپی کردن کوکی‌های موجود برای تست (اگر در j3 هست، دستی در j4/panel_sessions کپی کن)
    if not SESSIONS_DIR.exists():
        SESSIONS_DIR.mkdir(parents=True)
        print("پوشه panel_sessions ساخته شد. لطفا فایل کوکی ws_1_cookies.json را از پروژه اصلی به اینجا کپی کنید.")
        exit()

    # اطلاعات تست (این مقادیر را با اطلاعات واقعی یک کالای تست جایگزین کن)
    WORKSPACE_ID = 1 # شناسه پنل شما در دیتابیس
    TEST_VARIANT_ID = 12345678 # شناسه تنوع کالا (دقت کن کد DKPC نیست، کد Variant است)
    MIN_PRICE = 1500000  # کف قیمت به ریال یا تومان (بستگی به پنل دارد، معمولا ریال است)
    MAX_PRICE = 1700000  # سقف قیمت

    bot = DigikalaRepricer(
        workspace_id=WORKSPACE_ID,
        variant_id=TEST_VARIANT_ID,
        min_price=MIN_PRICE,
        max_price=MAX_PRICE,
        step_price=1000 # هزار تومان زیر قیمت رقیب
    )

    # اجرای یکباره برای تست
    bot.evaluate_and_act()
    
    # برای اجرای مداوم می‌توانید از حلقه زیر استفاده کنید:
    # while True:
    #     bot.evaluate_and_act()
    #     time.sleep(120) # هر 2 دقیقه یکبار چک می‌کند