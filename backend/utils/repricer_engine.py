import requests
import json
import time
import random
import os
from datetime import datetime
from pathlib import Path
from utils.manual_cookie_login import ManualCookieManager
from utils.formula_engine import calculate_buybox_price, calculate_min_price
from utils.strategies import AggressiveStrategy, ConservativeStrategy, StrategyInput

BASE_DIR = Path(__file__).resolve().parent.parent
SESSIONS_DIR = BASE_DIR / "panel_sessions"
SETTINGS_FILE = BASE_DIR / "repricer_settings.json"

DEFAULT_SETTINGS = {
    "lead_time": 2,
    "shipping_type": "seller",
    "max_per_order": 4,
    "request_delay_min": 3.0,
    "request_delay_max": 6.0,
    "rate_limit_backoff_base": 15,
    "max_retries": 3,
    "buybox_formula": "competitor_price - step_price",
    "min_price_formula": "",
    "auto_apply_min_price": False,
    "strategy_mode": "aggressive",   # aggressive | conservative | formula
    "dry_run": False,
    "variant_cooldown_seconds": 300,
    "max_price_change_percent": 8.0,
    "notify_webhook_url": "",
}


class DigikalaSellerClient:
    """کلاینت متمرکز برای API دیجی‌کالا با retry/jitter ساده."""
    RETRYABLE_STATUSES = {429, 502, 503, 504}

    def __init__(self, session: requests.Session, log):
        self.session = session
        self.log = log

    def request(self, method: str, url: str, *, json_payload=None, timeout=15, retries=3, backoff_base=4):
        last_response = None
        for attempt in range(retries):
            try:
                response = self.session.request(method, url, json=json_payload, timeout=timeout)
                last_response = response
                if response.status_code in self.RETRYABLE_STATUSES and attempt < retries - 1:
                    wait = backoff_base * (2 ** attempt) + random.uniform(0.2, 1.1)
                    self.log(f"⏳ retry {attempt + 1}/{retries} for {method} {url} in {wait:.1f}s (status={response.status_code})")
                    time.sleep(wait)
                    continue
                return response
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if attempt >= retries - 1:
                    raise
                wait = backoff_base * (2 ** attempt) + random.uniform(0.2, 1.1)
                self.log(f"🔁 network retry {attempt + 1}/{retries} for {method} {url}: {e} | wait={wait:.1f}s")
                time.sleep(wait)
        return last_response


class DigikalaRepricer:
    def __init__(self, workspace_id, log_callback=None):
        self.workspace_id = workspace_id
        self.log_callback = log_callback
        self.stats = {
            "total_updates": 0,
            "buybox_wins": 0,
            "cycles": 0,
            "last_cycle_time": None,
            "rate_limit_hits": 0,
            "failed_updates": 0,
            "last_error": "",
        }
        self.last_update_at = {}
        self.price_history = {}

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://seller.digikala.com",
            "Referer": "https://seller.digikala.com/pwa/variant-management",
            "x-api-client": "pwa",
        })
        self._load_cookies()
        self._set_csrf_header_from_cookies()
        token = os.getenv("DIGIKALA_AUTH_TOKEN", "").strip()
        if token:
            if not token.lower().startswith("bearer "):
                token = f"Bearer {token}"
            self.session.headers["Authorization"] = token
            self.log("🔐 Authorization token از env بارگذاری شد.")
        self.client = DigikalaSellerClient(self.session, self.log)
        self.aggressive_strategy = AggressiveStrategy()
        self.conservative_strategy = ConservativeStrategy()

    # ─── Logging ────────────────────────────────────────────────────────
    def log(self, msg):
        time_str = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{time_str}] {msg}"
        print(full_msg, flush=True)
        if self.log_callback:
            self.log_callback(full_msg)

    # ─── Settings ────────────────────────────────────────────────────────
    def _load_settings(self) -> dict:
        """بارگذاری تنظیمات از فایل - هر بار تازه خوانده می‌شود"""
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                return {**DEFAULT_SETTINGS, **saved}
            except Exception:
                pass
        return DEFAULT_SETTINGS.copy()

    # ─── Cookies ────────────────────────────────────────────────────────
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
                        self.session.cookies.set(
                            c['name'], c['value'],
                            domain=c.get('domain', '')
                        )
                        loaded += 1
                self.log(f"🍪 {loaded} کوکی بارگذاری شد (workspace {self.workspace_id})")
            except Exception as e:
                self.log(f"❌ خطا در خواندن کوکی: {e}")
        else:
            self.log(f"❌ کوکی workspace {self.workspace_id} یافت نشد. لاگین کنید.")

    def _set_csrf_header_from_cookies(self):
        """
        بعضی endpointهای Seller برای عملیات write به csrf-token وابسته‌اند.
        اگر csrf token در کوکی پیدا شود، هدرهای رایج ست می‌شوند.
        """
        csrf = (
            self.session.cookies.get("csrf_access_token")
            or self.session.cookies.get("csrftoken")
            or self.session.cookies.get("XSRF-TOKEN")
        )
        if csrf:
            self.session.headers.update({
                "x-csrf-token": csrf,
                "X-CSRFToken": csrf,
            })

    def _notify(self, message: str):
        webhook = self._load_settings().get("notify_webhook_url", "").strip()
        if not webhook:
            return
        try:
            requests.post(webhook, json={"text": message}, timeout=5)
        except Exception:
            pass

    def _is_in_cooldown(self, variant_id: str, cooldown_seconds: int) -> bool:
        last = self.last_update_at.get(variant_id)
        if not last:
            return False
        return (time.time() - last) < cooldown_seconds

    def _apply_delta_guard(self, current: int, target: int, max_pct: float) -> int:
        if current <= 0 or max_pct <= 0:
            return target
        limit = int(current * (max_pct / 100.0))
        if limit < 1000:
            limit = 1000
        upper = current + limit
        lower = max(1000, current - limit)
        return max(lower, min(upper, target))

    def get_auth_diagnostics(self) -> dict:
        """چک سریع وضعیت احراز هویت و دسترسی read/write."""
        csrf_exists = bool(
            self.session.headers.get("x-csrf-token")
            or self.session.headers.get("X-CSRFToken")
        )
        try:
            res = self.client.request(
                "GET",
                "https://seller.digikala.com/api/v2/variants?page=1&size=1&sort=product_variant_id&order=desc",
                timeout=12,
                retries=1,
            )
            read_status = res.status_code if res is not None else 0
        except Exception:
            read_status = 0
        return {
            "workspace_id": self.workspace_id,
            "cookie_count": len(self.session.cookies),
            "has_authorization_header": bool(self.session.headers.get("Authorization")),
            "has_csrf_header": csrf_exists,
            "variants_read_status": read_status,
            "is_read_auth_ok": read_status == 200,
        }

    # ─── Human-like delay ───────────────────────────────────────────────
    def _sleep_human(self, settings: dict = None):
        """تاخیر تصادفی برای شبیه‌سازی رفتار انسانی"""
        if settings is None:
            settings = self._load_settings()
        delay = random.uniform(
            settings.get("request_delay_min", 3.0),
            settings.get("request_delay_max", 6.0),
        )
        time.sleep(delay)

    # ─── Variants ────────────────────────────────────────────────────────
    def get_my_variants(self, page=1, size=50):
        url = (
            f"https://seller.digikala.com/api/v2/variants"
            f"?page={page}&size={size}&sort=product_variant_id&order=desc"
        )
        try:
            response = self.client.request("GET", url, timeout=15, retries=2, backoff_base=4)
            if response.status_code == 401:
                self.log("⚠️ کوکی منقضی شده! نیاز به لاگین مجدد.")
                return {"success": False, "variants": [], "total_pages": 1, "auth_error": True}
            if response.status_code == 429:
                self.log("⏸ محدودیت 429 هنگام دریافت محصولات! ۲۰ ثانیه صبر...")
                time.sleep(20)
                return {"success": False, "variants": [], "total_pages": 1}
            if response.status_code == 200:
                data = response.json()
                items = data.get("data", {}).get("items", [])
                total_pages = data.get("data", {}).get("pager", {}).get("total_pages", 1)

                variants = []
                for item in items:
                    if item.get("active") and item.get("marketplace_seller_stock", 0) > 0:
                        variants.append({
                            "variant_id":       item.get("product_variant_id"),
                            "title":            item.get("product_title"),
                            "is_buy_box_winner": item.get("is_buy_box_winner"),
                            "current_price":    item.get("price_sale"),
                            "reference_price":  item.get("price_list"),
                            "buy_box_price":    item.get("buy_box_price"),
                            "stock":            item.get("marketplace_seller_stock", 0),
                            "seller_stock":     item.get("seller_stock", 0),
                        })
                return {"success": True, "variants": variants, "total_pages": total_pages}
            return {"success": False, "variants": [], "total_pages": 1}
        except Exception as e:
            self.log(f"خطای شبکه: {e}")
            return {"success": False, "variants": [], "total_pages": 1}

    # ─── Competitors ─────────────────────────────────────────────────────
    def get_competitor_price(self, variant_id):
        """
        برگشت: (lowest_competitor_price, i_am_alone_in_buybox)
        """
        url = f"https://seller.digikala.com/api/v1/variants/{variant_id}/competitors/"
        try:
            response = self.client.request("GET", url, timeout=10, retries=2, backoff_base=4)
            if response.status_code == 429:
                self.log(f"⏸ محدودیت 429 هنگام بررسی رقبا! ۱۵ ثانیه صبر...")
                time.sleep(15)
                return None, False
            if response.status_code == 200:
                competitors = response.json().get('data', {}).get('competitors', [])
                if not competitors:
                    return None, True  # تنهاییم

                lowest_comp = float('inf')
                comp_count = 0

                for comp in competitors:
                    if not comp.get('is_me'):
                        price = comp.get('price', float('inf'))
                        if price < lowest_comp:
                            lowest_comp = price
                        comp_count += 1

                if comp_count == 0:
                    return None, True
                return lowest_comp, False
            return None, False
        except Exception:
            return None, False

    # ─── Price Update (POST - مطابق test_api.py) ─────────────────────────
    def update_my_price(self, variant_id, new_price, silent=False, stock=None, lead_time=None):
        """
        آپدیت قیمت با POST (مطابق test_api.py) + مدیریت کامل 429 با backoff نمایی
        """
        url = "https://seller.digikala.com/api/v2/variants/bulk"
        settings = self._load_settings()

        variant_payload = {
            "variant_id":         int(variant_id),
            "selling_price":      int(new_price),
            "shipping_type":      settings.get("shipping_type", "seller"),
            "seller_lead_time":   int(lead_time) if lead_time is not None else settings.get("lead_time", 2),
            "maximum_per_order":  settings.get("max_per_order", 4),
        }

        if stock is not None:
            variant_payload["seller_stock"] = int(stock)

        payload = {"variants": [variant_payload]}
        max_retries = settings.get("max_retries", 3)
        backoff_base = settings.get("rate_limit_backoff_base", 15)
        dry_run = bool(settings.get("dry_run", False))

        if dry_run:
            self.log(f"🧪 [DRY-RUN] [تنوع {variant_id}] قیمت پیشنهادی: {new_price:,}")
            return {"success": True, "message": "dry_run", "dry_run": True}

        for attempt in range(max_retries):
            try:
                # تاخیر تصادفی شبیه انسان
                self._sleep_human(settings)

                # ───  POST (نه PUT) ───
                response = self.client.request(
                    "POST",
                    url,
                    json_payload=payload,
                    timeout=10,
                    retries=1,
                    backoff_base=backoff_base,
                )

                # ─── 429: backoff نمایی ───────────────────────────────
                if response.status_code == 429:
                    wait = backoff_base * (2 ** attempt)   # 15s → 30s → 60s
                    self.stats["rate_limit_hits"] += 1
                    self.log(f"⏸ محدودیت 429! (تلاش {attempt+1}/{max_retries}) {wait} ثانیه صبر...")
                    time.sleep(wait)
                    continue

                # ─── 401: کوکی تموم شده ──────────────────────────────
                if response.status_code == 401:
                    self.log("⚠️ کوکی منقضی شده! نیاز به لاگین مجدد.")
                    return {"success": False, "message": "auth_error"}

                # ─── موفق ─────────────────────────────────────────────
                if response.status_code in (200, 201):
                    resp_json = response.json()
                    if resp_json.get("status") is False:
                        err = resp_json.get("message") or "status=false"
                        if not silent:
                            self.log(f"⚠️ [تنوع {variant_id}] پاسخ ناموفق: {err}")
                        return {"success": False, "message": str(err)}
                    errors = resp_json.get("data", {}).get("errors", [])
                    if not errors:
                        if not silent:
                            self.log(f"✅ [تنوع {variant_id}] ← {new_price:,} تومان")
                        self.stats["total_updates"] += 1
                        self.last_update_at[str(variant_id)] = time.time()
                        self.price_history[str(variant_id)] = {
                            "price": int(new_price),
                            "at": datetime.now().isoformat(),
                        }
                        return {"success": True, "message": "OK"}
                    else:
                        error_msg = str(errors)
                        if not silent:
                            self.log(f"⚠️ [تنوع {variant_id}] رد شد: {error_msg}")
                        self.stats["failed_updates"] += 1
                        self.stats["last_error"] = error_msg
                        return {"success": False, "message": error_msg}

                # ─── سایر خطاها ───────────────────────────────────────
                try:
                    error_msg = response.json().get('message', str(response.status_code))
                except Exception:
                    error_msg = f"HTTP {response.status_code}"
                if not silent:
                    self.log(f"⚠️ [تنوع {variant_id}] خطا: {error_msg}")
                self.stats["failed_updates"] += 1
                self.stats["last_error"] = str(error_msg)
                return {"success": False, "message": str(error_msg)}

            except requests.exceptions.Timeout:
                self.log(f"⏱ [تنوع {variant_id}] timeout (تلاش {attempt+1})")
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
            except requests.exceptions.ConnectionError:
                self.log(f"🔌 [تنوع {variant_id}] خطای اتصال (تلاش {attempt+1})")
                if attempt < max_retries - 1:
                    time.sleep(8)
                    continue
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                if not silent:
                    self.log(f"❌ خطای شبکه: {e}")
                self.stats["failed_updates"] += 1
                self.stats["last_error"] = str(e)
                return {"success": False, "message": str(e)}

        return {"success": False, "message": "max retries exceeded"}

    # ─── Discover Bounds ─────────────────────────────────────────────────
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
            test_price = int(round((reference_price * (1 + mid)) / 1000.0) * 1000)
            self.log(f"  سقف [{i+1}/10] +{round(mid*100, 1)}% → {test_price:,}")

            res = self.update_my_price(variant_id, test_price, silent=True)
            if res['success']:
                max_valid = test_price
                low_pct = mid
                self.log(f"  ✔️ تایید! بازگشت به {current_price:,}")
                self.update_my_price(variant_id, current_price, silent=True)
            else:
                high_pct = mid

        # --- فاز ۲: کف ---
        self.log(">> فاز ۲: جستجوی کف مجاز...")
        min_valid = current_price
        low_pct, high_pct = 0.0, 0.5

        for i in range(10):
            mid = (low_pct + high_pct) / 2
            test_price = int(round((reference_price * (1 - mid)) / 1000.0) * 1000)
            if test_price <= 0:
                high_pct = mid
                continue

            self.log(f"  کف [{i+1}/10] -{round(mid*100, 1)}% → {test_price:,}")
            res = self.update_my_price(variant_id, test_price, silent=True)
            if res['success']:
                min_valid = test_price
                low_pct = mid
                self.log(f"  ✔️ تایید! بازگشت به {current_price:,}")
                self.update_my_price(variant_id, current_price, silent=True)
            else:
                high_pct = mid

        self.update_my_price(variant_id, current_price, silent=True)
        self.log(f"🎯 نتیجه: کف={min_valid:,} | سقف={max_valid:,}")
        return {"success": True, "min_price": min_valid, "max_price": max_valid}

    # ─── Apply Min Price Formula ──────────────────────────────────────────
    def apply_min_price_formula_to_all(self, product_configs: dict, formula: str, step_price: int = 1000) -> dict:
        """
        اعمال فرمول کف قیمت به همه محصولات تنظیم‌شده
        فقط کف قیمت محاسبه می‌شود - قیمت واقعی دیجی‌کالا تغییر نمی‌کند
        """
        self.log(f"📐 شروع اعمال فرمول کف قیمت: {formula}")
        updated = {}
        errors = {}

        all_variants = []
        page, total_pages = 1, 1
        while page <= total_pages:
            res = self.get_my_variants(page)
            if not res['success']:
                break
            total_pages = res['total_pages']
            all_variants.extend(res['variants'])
            page += 1

        for item in all_variants:
            vid = str(item['variant_id'])
            ref = int(item.get('reference_price') or item.get('current_price') or 0)
            cur = int(item.get('current_price') or 0)

            try:
                min_p = calculate_min_price(formula, ref, cur, step_price)
                conf = product_configs.get(vid, {})
                updated[vid] = {
                    **conf,
                    "min_price": min_p,
                }
                self.log(f"  📌 [{item['title'][:25]}] کف جدید: {min_p:,}")
            except ValueError as e:
                errors[vid] = str(e)
                self.log(f"  ⚠️ [{item['title'][:25]}] خطا در فرمول: {e}")

        self.log(f"📐 پایان اعمال فرمول | موفق: {len(updated)} | خطا: {len(errors)}")
        return {"updated": updated, "errors": errors}

    # ─── Main Loop ────────────────────────────────────────────────────────
    def evaluate_and_act_all(self, product_configs: dict, step_price: int = 1000) -> dict:
        """
        هسته اصلی رقابت - با پشتیبانی از فرمول و استراتژی‌های مختلف
        """
        self.stats["cycles"] += 1
        self.stats["last_cycle_time"] = datetime.now().isoformat()
        settings = self._load_settings()
        strategy = settings.get("strategy_mode", "aggressive")
        buybox_formula = settings.get("buybox_formula", "competitor_price - step_price")
        cooldown_seconds = int(settings.get("variant_cooldown_seconds", 300))
        max_delta_pct = float(settings.get("max_price_change_percent", 8.0))
        dry_run = bool(settings.get("dry_run", False))

        self.log(f"━━━ چرخه #{self.stats['cycles']} | استراتژی: {strategy} | dry_run={dry_run} ━━━")

        all_variants = []
        page, total_pages = 1, 1
        while page <= total_pages:
            res = self.get_my_variants(page)
            if not res['success']:
                break
            total_pages = res['total_pages']
            all_variants.extend(res['variants'])
            page += 1

        buybox_count = updated_count = skipped_count = 0

        for item in all_variants:
            vid = str(item['variant_id'])
            if vid not in product_configs:
                continue

            conf = product_configs[vid]
            min_p = int(conf.get('min_price') or 0)
            max_p = int(conf.get('max_price') or 0)
            current = int(item.get('current_price') or 0)
            ref_price = int(item.get('reference_price') or current)
            buy_box_p = int(item.get('buy_box_price') or 0)

            if not min_p or not max_p:
                continue
            if self._is_in_cooldown(vid, cooldown_seconds):
                skipped_count += 1
                continue

            comp_price, i_am_alone = self.get_competitor_price(vid)
            time.sleep(0.5)

            # ── ۱. تنها در بازار ─────────────────────────────────────────
            if i_am_alone or comp_price is None or comp_price == float('inf'):
                if item['is_buy_box_winner']:
                    self.stats["buybox_wins"] += 1
                    buybox_count += 1
                    # سعی کن قیمت را به آرامی به سقف برسانی
                    relaxed_target = min(current + step_price * 2, max_p)
                    if relaxed_target > current:
                        relaxed_target = self._apply_delta_guard(current, relaxed_target, max_delta_pct)
                        self.log(f"📈 [{item['title'][:25]}] تنها در میدان! ↑ {current:,} → {relaxed_target:,}")
                        self.update_my_price(vid, relaxed_target)
                        updated_count += 1
                continue

            comp_price = int(comp_price)

            # ── ۲. BuyBox داریم + رقیب هم هست ───────────────────────────
            if item['is_buy_box_winner']:
                self.stats["buybox_wins"] += 1
                buybox_count += 1
                # اگر فاصله از رقیب کافی است، قیمت را بالا ببر
                if current + step_price < comp_price and current + step_price <= max_p:
                    relaxed = min(comp_price - 1, max_p)
                    relaxed = max(relaxed, min_p)
                    if relaxed > current:
                        relaxed = self._apply_delta_guard(current, relaxed, max_delta_pct)
                        self.log(f"💰 [{item['title'][:25]}] BuyBox! بهینه سود: {current:,} → {relaxed:,}")
                        self.update_my_price(vid, relaxed)
                        updated_count += 1
                continue

            # ── ۳. BuyBox نداریم - باید بجنگیم ──────────────────────────
            # محاسبه قیمت هدف بر اساس استراتژی
            try:
                decision_input = StrategyInput(
                    competitor_price=comp_price,
                    current_price=current,
                    reference_price=ref_price,
                    step_price=step_price,
                    min_price=min_p,
                    max_price=max_p,
                    buy_box_price=buy_box_p,
                )
                if strategy == "formula" and buybox_formula:
                    target_price = calculate_buybox_price(
                        buybox_formula, comp_price, ref_price,
                        current, step_price, min_p, buy_box_p
                    )
                elif strategy == "conservative":
                    target_price = self.conservative_strategy.decide(decision_input)
                    if target_price is None:
                        self.log(f"🛡 [{item['title'][:25]}] محافظه‌کار: فاصله کم - صبر می‌کنیم")
                        skipped_count += 1
                        continue
                else:  # aggressive (پیش‌فرض)
                    target_price = self.aggressive_strategy.decide(decision_input)

            except ValueError as e:
                self.log(f"⚠️ [{item['title'][:25]}] خطای فرمول: {e}")
                skipped_count += 1
                continue

            # ── بررسی محدوده مجاز ────────────────────────────────────────
            if target_price < min_p:
                self.log(f"⛔ [{item['title'][:25]}] رقیب ({comp_price:,}) زیر کف ({min_p:,}) — صبر")
                skipped_count += 1
                continue

            target_price = min(target_price, max_p)
            target_price = self._apply_delta_guard(current, target_price, max_delta_pct)

            # آپدیت فقط اگر تغییر معنادار است
            if abs(target_price - current) >= step_price:
                self.log(f"⚔️ [{item['title'][:25]}] {current:,} → {target_price:,} (رقیب: {comp_price:,})")
                self.update_my_price(vid, target_price)
                updated_count += 1

        rate_hits = self.stats["rate_limit_hits"]
        self.log(
            f"━━━ پایان چرخه | BuyBox: {buybox_count} | "
            f"آپدیت: {updated_count} | رد: {skipped_count} | "
            f"429: {rate_hits} ━━━"
        )
        if self.stats.get("failed_updates", 0) > 0 and self.stats["failed_updates"] % 20 == 0:
            self._notify(f"repricer warning: failed_updates={self.stats['failed_updates']} last_error={self.stats.get('last_error','')}")
        return {
            "buybox_count": buybox_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "rate_limit_hits": rate_hits,
        }
