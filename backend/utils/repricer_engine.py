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
        self.stats = {
            "total_updates": 0,
            "buybox_wins": 0,
            "cycles": 0,
            "last_cycle_time": None
        }

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://seller.digikala.com",
            "Referer": "https://seller.digikala.com/pwa/variant-management",
            "x-api-client": "pwa"
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
                    loaded = 0
                    for c in data.get('cookies', []):
                        if 'name' in c and 'value' in c:
                            self.session.cookies.set(c['name'], c['value'], domain=c.get('domain', ''))
                            loaded += 1
                self.log(f"🍪 {loaded} کوکی بارگذاری شد (workspace {self.workspace_id})")
            except Exception as e:
                self.log(f"❌ خطا در خواندن کوکی: {e}")
        else:
            self.log(f"❌ کوکی workspace {self.workspace_id} یافت نشد. لاگین کنید.")

    def get_my_variants(self, page=1, size=50):
        url = f"https://seller.digikala.com/api/v2/variants?page={page}&size={size}&sort=product_variant_id&order=desc"
        try:
            response = self.session.get(url, timeout=15)
            if response.status_code == 401:
                self.log("⚠️ کوکی منقضی شده! نیاز به لاگین مجدد.")
                return {"success": False, "variants": [], "total_pages": 1, "auth_error": True}
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
                            "buy_box_price": item.get("buy_box_price"),
                            "stock": item.get("marketplace_seller_stock", 0),
                            "seller_stock": item.get("seller_stock", 0),
                        })
                return {"success": True, "variants": variants, "total_pages": total_pages}
            else:
                return {"success": False, "variants": [], "total_pages": 1}
        except Exception as e:
            self.log(f"خطای شبکه: {e}")
            return {"success": False, "variants": [], "total_pages": 1}

    def get_competitor_price(self, variant_id):
        """
        برگشت: (lowest_competitor_price, i_am_alone_in_buybox)
        اگر i_am_alone_in_buybox=True یعنی رقیبی نیست
        """
        url = f"https://seller.digikala.com/api/v1/variants/{variant_id}/competitors/"
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                competitors = response.json().get('data', {}).get('competitors', [])
                if not competitors:
                    return None, True  # تنهاییم

                my_price = None
                lowest_comp = float('inf')
                comp_count = 0

                for comp in competitors:
                    if comp.get('is_me'):
                        my_price = comp.get('price')
                    else:
                        price = comp.get('price', float('inf'))
                        if price < lowest_comp:
                            lowest_comp = price
                        comp_count += 1

                if comp_count == 0:
                    return None, True  # رقیبی نداریم

                return lowest_comp, False
            return None, False
        except:
            return None, False

    def update_my_price(self, variant_id, new_price, silent=False, stock=None, lead_time=None):
        url = "https://seller.digikala.com/api/v2/variants/bulk"

        variant_payload = {
            "variant_id": int(variant_id),
            "selling_price": int(new_price)
        }

        # اگر stock و lead_time داده شد، همزمان آپدیت می‌کنیم
        if stock is not None:
            variant_payload["seller_stock"] = int(stock)
            variant_payload["shipping_type"] = "seller"
        if lead_time is not None:
            variant_payload["seller_lead_time"] = int(lead_time)

        payload = {"variants": [variant_payload]}

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.put(url, json=payload, timeout=10)

                if response.status_code == 429:
                    self.log(f"⏸ محدودیت rate limit! ۱۵ ثانیه صبر...")
                    time.sleep(15)
                    continue

                if response.status_code == 401:
                    self.log("⚠️ کوکی منقضی! نیاز به لاگین مجدد.")
                    return {"success": False, "message": "auth_error"}

                if response.status_code == 200:
                    resp_json = response.json()
                    errors = resp_json.get("data", {}).get("errors", [])

                    if not errors:
                        if not silent:
                            self.log(f"✅ [تنوع {variant_id}] ← {new_price:,} تومان")
                        self.stats["total_updates"] += 1
                        return {"success": True, "message": "OK"}
                    else:
                        error_msg = str(errors)
                        if not silent:
                            self.log(f"⚠️ [تنوع {variant_id}] رد شد: {error_msg}")
                        return {"success": False, "message": error_msg}
                else:
                    try:
                        error_msg = response.json().get('message', str(response.status_code))
                    except:
                        error_msg = f"HTTP {response.status_code}"
                    if not silent:
                        self.log(f"⚠️ [تنوع {variant_id}] خطا: {error_msg}")
                    return {"success": False, "message": str(error_msg)}

            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                if not silent:
                    self.log(f"❌ خطای شبکه: {e}")
                return {"success": False, "message": str(e)}

        return {"success": False, "message": "max retries exceeded"}

    def discover_price_bounds(self, variant_id, reference_price, current_price):
        """کشف دقیق کف و سقف مجاز با binary search"""
        if not reference_price or reference_price == 0:
            reference_price = current_price

        self.log(f"🔍 شروع اسکن برای تنوع {variant_id} | مرجع: {reference_price:,}")

        # --- فاز ۱: سقف ---
        self.log(">> فاز ۱: جستجوی سقف مجاز...")
        max_valid = current_price
        low_pct, high_pct = 0.0, 0.8

        for i in range(10):
            mid = (low_pct + high_pct) / 2
            test_price = int(round(reference_price * (1 + mid) / 1000.0) * 1000)
            self.log(f"  سقف [{i+1}/10] +{round(mid*100, 1)}% → {test_price:,}")

            res = self.update_my_price(variant_id, test_price, silent=True)
            time.sleep(3)

            if res['success']:
                max_valid = test_price
                low_pct = mid
                self.log(f"  ✔️ تایید! بازگشت به {current_price:,}")
                self.update_my_price(variant_id, current_price, silent=True)
                time.sleep(1)
            else:
                high_pct = mid

        # --- فاز ۲: کف ---
        self.log(">> فاز ۲: جستجوی کف مجاز...")
        min_valid = current_price
        low_pct, high_pct = 0.0, 0.5

        for i in range(10):
            mid = (low_pct + high_pct) / 2
            test_price = int(round(reference_price * (1 - mid) / 1000.0) * 1000)
            if test_price <= 0:
                high_pct = mid
                continue

            self.log(f"  کف [{i+1}/10] -{round(mid*100, 1)}% → {test_price:,}")
            res = self.update_my_price(variant_id, test_price, silent=True)
            time.sleep(3)

            if res['success']:
                min_valid = test_price
                low_pct = mid
                self.log(f"  ✔️ تایید! بازگشت به {current_price:,}")
                self.update_my_price(variant_id, current_price, silent=True)
                time.sleep(1)
            else:
                high_pct = mid

        # بازگرداندن به قیمت اصلی
        self.update_my_price(variant_id, current_price, silent=True)
        self.log(f"🎯 نتیجه: کف={min_valid:,} | سقف={max_valid:,}")
        return {"success": True, "min_price": min_valid, "max_price": max_valid}

    def evaluate_and_act_all(self, product_configs, step_price=1000):
        """
        هسته اصلی رقابت: برای هر محصول تصمیم هوشمند می‌گیرد
        استراتژی: 
          - اگر buy_box داریم: بررسی کنیم می‌توانیم قیمت را کمی بالا ببریم
          - اگر buy_box نداریم: با step_price زیر ارزانترین رقیب بزنیم
          - اگر رقیب از کف ما پایین‌تر است: صبر کنیم (جنگ مرگ‌بار نمی‌کنیم)
        """
        self.stats["cycles"] += 1
        self.stats["last_cycle_time"] = datetime.now().isoformat()
        self.log(f"━━━ چرخه #{self.stats['cycles']} شروع شد ━━━")

        all_variants = []
        page = 1
        total_pages = 1
        while page <= total_pages:
            res = self.get_my_variants(page)
            if not res['success']:
                break
            total_pages = res['total_pages']
            all_variants.extend(res['variants'])
            page += 1

        buybox_count = 0
        updated_count = 0
        skipped_count = 0

        for item in all_variants:
            vid = str(item['variant_id'])
            if vid not in product_configs:
                continue

            conf = product_configs[vid]
            min_p = int(conf.get('min_price', 0))
            max_p = int(conf.get('max_price', float('inf')))
            current = int(item.get('current_price', 0))

            if not min_p or not max_p:
                continue  # بدون config مشخص، کاری نمی‌کنیم

            comp_price, i_am_alone = self.get_competitor_price(vid)
            time.sleep(0.5)

            # ۱. تنها در بازارم - سعی کن قیمت را به سقف برسانی (افزایش تدریجی)
            if i_am_alone or comp_price is None or comp_price == float('inf'):
                if item['is_buy_box_winner']:
                    self.stats["buybox_wins"] += 1
                    buybox_count += 1
                    # اگر قیمت فعلی از سقف پایین‌تر است، کمی بالا ببر
                    relaxed_target = min(current + step_price * 2, max_p)
                    if relaxed_target > current and relaxed_target <= max_p:
                        self.log(f"📈 [{item['title'][:25]}] تنها در میدان! قیمت بالا می‌رود: {current:,} → {relaxed_target:,}")
                        self.update_my_price(vid, relaxed_target)
                        updated_count += 1
                        time.sleep(1)
                continue

            comp_price = int(comp_price)

            # ۲. اگر buy_box داریم ولی رقیب هم هست
            if item['is_buy_box_winner']:
                self.stats["buybox_wins"] += 1
                buybox_count += 1
                # بررسی: آیا می‌توانیم قیمت را کمی بالا ببریم بدون از دست دادن buy_box؟
                # اگر قیمت ما حداقل step_price از رقیب ارزان‌تر است، جا داریم بالا بریم
                if current + step_price < comp_price and current + step_price <= max_p:
                    relaxed = min(comp_price - 1, max_p)
                    relaxed = max(relaxed, min_p)
                    if relaxed > current:
                        self.log(f"💰 [{item['title'][:25]}] BuyBox داریم! بهینه‌سازی سود: {current:,} → {relaxed:,}")
                        self.update_my_price(vid, relaxed)
                        updated_count += 1
                        time.sleep(1)
                continue

            # ۳. buy_box نداریم - باید بجنگیم
            target_price = comp_price - step_price

            if target_price < min_p:
                self.log(f"⛔ [{item['title'][:25]}] رقیب ({comp_price:,}) زیر کف ماست ({min_p:,}). صبر می‌کنیم.")
                skipped_count += 1
                continue

            if target_price > max_p:
                target_price = max_p

            # اگر قیمت تغییر معناداری دارد
            if abs(target_price - current) >= step_price:
                self.log(f"⚔️ [{item['title'][:25]}] حمله! {current:,} → {target_price:,} (رقیب: {comp_price:,})")
                self.update_my_price(vid, target_price)
                updated_count += 1
                time.sleep(1)

        self.log(f"━━━ پایان چرخه | BuyBox: {buybox_count} | آپدیت: {updated_count} | رد: {skipped_count} ━━━")
        return {
            "buybox_count": buybox_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count
        }