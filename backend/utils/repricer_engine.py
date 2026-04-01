"""
backend/utils/repricer_engine.py

موتور اصلی ربات قیمت‌گذاری — ارتقا یافته با فرمول هوشمند و بیشینه‌سازی سود
"""
import requests
import json
import time
import random
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Tuple, Dict, Any

from utils.manual_cookie_login import ManualCookieManager
from utils.strategies import StrategyInput, get_strategy, STRATEGY_INFO

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
    "default_strategy": "aggressive",
    "default_step": 1000,
    "dry_run": False,
    "variant_cooldown_seconds": 300,
    "notify_webhook_url": "",
    "rate_limit_pause_seconds": 180,
    "max_consecutive_failures": 10,
}


class DigikalaSellerClient:
    """HTTP client با retry/backoff برای Seller API"""
    RETRYABLE = {429, 502, 503, 504}

    def __init__(self, session: requests.Session, log: Callable):
        self.session = session
        self.log = log

    def request(self, method: str, url: str, *, json_payload=None,
                timeout=15, retries=3, backoff_base=4) -> Optional[requests.Response]:
        last = None
        for attempt in range(retries):
            try:
                resp = self.session.request(method, url, json=json_payload, timeout=timeout)
                last = resp
                if resp.status_code in self.RETRYABLE and attempt < retries - 1:
                    wait = backoff_base * (2 ** attempt) + random.uniform(0.2, 1.0)
                    self.log(f"⏳ retry {attempt+1}/{retries} | status={resp.status_code} | wait={wait:.1f}s")
                    time.sleep(wait)
                    continue
                return resp
            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt >= retries - 1:
                    raise
                wait = backoff_base * (2 ** attempt) + random.uniform(0.2, 1.0)
                self.log(f"🔁 network retry {attempt+1}/{retries} | {e} | wait={wait:.1f}s")
                time.sleep(wait)
        return last


class DigikalaRepricer:
    def __init__(self, workspace_id: int, log_callback: Callable = None):
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
            "consecutive_failures": 0,
            "paused_until": 0.0,
        }
        self.last_update_at: dict[str, float] = {}

        # ─── Seller session ──────────────────────────────────────
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://seller.digikala.com",
            "Referer": "https://seller.digikala.com/pwa/variant-management",
            "x-api-client": "pwa",
        })
        self._load_cookies()
        self._set_csrf_header()

        token = os.getenv("DIGIKALA_AUTH_TOKEN", "").strip()
        if token:
            if not token.lower().startswith("bearer "):
                token = f"Bearer {token}"
            self.session.headers["Authorization"] = token
            self.log("🔐 Authorization از env بارگذاری شد.")

        self.client = DigikalaSellerClient(self.session, self.log)

        # ─── Public session ──────────
        self.public_session = requests.Session()
        self.public_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "x-web-client": "desktop",
            "x-web-client-id": "web",
        })

    def log(self, msg: str):
        full = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        print(full, flush=True)
        if self.log_callback:
            self.log_callback(full)

    def _load_settings(self) -> dict:
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    return {**DEFAULT_SETTINGS, **json.load(f)}
            except Exception:
                pass
        return DEFAULT_SETTINGS.copy()

    def _load_cookies(self):
        cm = ManualCookieManager(SESSIONS_DIR)
        status = cm.check_cookie_validity(self.workspace_id)
        if not status["valid"]:
            self.log(f"❌ کوکی workspace {self.workspace_id} یافت نشد.")
            return
        path = cm.get_cookie_path(self.workspace_id)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded = 0
            for c in data.get("cookies", []):
                if "name" in c and "value" in c:
                    self.session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))
                    loaded += 1
            self.log(f"🍪 {loaded} کوکی بارگذاری شد")
        except Exception as e:
            self.log(f"❌ خطا در بارگذاری کوکی: {e}")

    def _set_csrf_header(self):
        csrf = (
            self.session.cookies.get("csrf_access_token")
            or self.session.cookies.get("csrftoken")
            or self.session.cookies.get("XSRF-TOKEN")
        )
        if csrf:
            self.session.headers.update({"x-csrf-token": csrf, "X-CSRFToken": csrf})

    def _is_paused(self) -> bool:
        return time.time() < self.stats["paused_until"]

    def _pause(self, seconds: int, reason: str):
        until = time.time() + max(1, seconds)
        self.stats["paused_until"] = until
        self.log(f"⏸ متوقف تا {datetime.fromtimestamp(until).strftime('%H:%M:%S')} | {reason}")

    def _on_success(self):
        self.stats["consecutive_failures"] = 0

    def _on_failure(self, reason: str):
        self.stats["failed_updates"] += 1
        self.stats["consecutive_failures"] += 1
        self.stats["last_error"] = reason
        s = self._load_settings()
        if self.stats["consecutive_failures"] >= int(s.get("max_consecutive_failures", 10)):
            self._pause(int(s.get("rate_limit_pause_seconds", 180)),
                        f"consecutive failures={self.stats['consecutive_failures']}")
            self.stats["consecutive_failures"] = 0

    def _in_cooldown(self, variant_id: str, seconds: int) -> bool:
        last = self.last_update_at.get(variant_id)
        return bool(last and (time.time() - last) < seconds)

    def _sleep(self, s: dict = None):
        if s is None:
            s = self._load_settings()
        time.sleep(random.uniform(
            s.get("request_delay_min", 3.0),
            s.get("request_delay_max", 6.0),
        ))

    # =========================================================================
    # ─── GET: قیمت و رتبه‌ی رقبا (ارتقا یافته) ────────────────────────────────
    # =========================================================================
    def get_competitor_prices(self, product_id: int, my_seller_id: int) -> Tuple[Optional[int], bool, Dict[str, Any]]:
        """
        برگشت: (ارزان‌ترین_رقیب, تنها_در_بازار, اطلاعات_کامل_برنده)
        """
        url = f"https://api.digikala.com/v2/product/{product_id}/"
        try:
            resp = self.public_session.get(url, timeout=10)
            if resp.status_code != 200:
                self.log(f"⚠️ public API status={resp.status_code} برای product {product_id}")
                return None, False, {}

            data = resp.json()
            product_data = data.get("data", {}).get("product", {})
            
            # استخراج لیست تنوع‌ها و تنوع برنده (default_variant)
            variants = product_data.get("variants", [])
            default_variant = product_data.get("default_variant", {})
            winner_variant_id = default_variant.get("id")

            prices = []
            winner_info = {}
            
            for v in variants:
                seller = v.get("seller", {})
                seller_id = seller.get("id")
                price = v.get("price", {}).get("selling_price", 0)
                status = v.get("status", "") # استفاده از status به جای stock
                
                # آیا این تنوع، همان تنوع برنده (default_variant) است؟
                is_winner = (v.get("id") == winner_variant_id)
                
                if is_winner:
                    winner_info = {
                        "seller_id": seller_id,
                        "price": price,
                        "rating": seller.get("rating", {}).get("total_rate", 0),
                        "votes": seller.get("rating", {}).get("total_count", 0) # تعداد آرا برای تشخیص غول
                    }

                # فقط رقبایی که وضعیتشان marketable (موجود) است را به لیست رقبا اضافه کن
                if seller_id and seller_id != my_seller_id and price > 0 and status == "marketable":
                    prices.append(price)

            if not prices:
                # اگر لیست خالی است، یعنی شما تنها فروشنده موجود هستید
                return None, True, winner_info

            # برگرداندن قیمت ارزان‌ترین رقیب
            return min(prices), False, winner_info

        except Exception as e:
            self.log(f"❌ خطا در دریافت قیمت رقبا product={product_id}: {e}")
            return None, False, {}

    def get_my_variants(self, page: int = 1, size: int = 50) -> dict:
        url = (
            f"https://seller.digikala.com/api/v2/variants"
            f"?page={page}&size={size}&sort=product_variant_id&order=desc"
        )
        try:
            resp = self.client.request("GET", url, timeout=15, retries=2)
            if resp is None:
                return {"success": False, "variants": [], "total_pages": 1}
            if resp.status_code == 401:
                self.log("⚠️ کوکی منقضی! نیاز به لاگین مجدد.")
                return {"success": False, "variants": [], "total_pages": 1, "auth_error": True}
            if resp.status_code == 429:
                self.log("⏸ 429 هنگام دریافت تنوع‌ها — ۲۰ ثانیه صبر...")
                time.sleep(20)
                return {"success": False, "variants": [], "total_pages": 1}
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", {}).get("items", [])
                total_pages = data.get("data", {}).get("pager", {}).get("total_pages", 1)
                variants = []
                for item in items:
                    if item.get("active") and item.get("marketplace_seller_stock", 0) > 0:
                        variants.append({
                            "variant_id":         item.get("product_variant_id"),
                            "product_id":         item.get("product_id"),
                            "title":              item.get("product_title"),
                            "is_buy_box_winner":  item.get("is_buy_box_winner"),
                            "current_price":      item.get("price_sale"),
                            "reference_price":    item.get("price_list"),
                            "buy_box_price":      item.get("buy_box_price"),
                            "stock":              item.get("marketplace_seller_stock", 0),
                            "seller_stock":       item.get("seller_stock", 0),
                        })
                return {"success": True, "variants": variants, "total_pages": total_pages}
            return {"success": False, "variants": [], "total_pages": 1}
        except Exception as e:
            self.log(f"❌ خطای شبکه get_my_variants: {e}")
            return {"success": False, "variants": [], "total_pages": 1}

    def update_my_price(self, variant_id: str, new_price: int, stock: int = 1, silent: bool = False) -> dict:
        url = "https://seller.digikala.com/api/v2/variants/bulk"
        s = self._load_settings()

        if bool(s.get("dry_run", False)):
            self.log(f"🧪 [DRY-RUN] تنوع {variant_id} → {new_price:,}")
            return {"success": True, "dry_run": True}

        # پیلود دقیقاً منطبق با ساختار ارسالی دیجی‌کالا در فایل شما
        payload = {"variants": [{
            "variant_id":        int(variant_id),
            "selling_price":     int(new_price),
            "shipping_type":     s.get("shipping_type", "seller"),
            "seller_lead_time":  int(s.get("lead_time", 2)),
            "maximum_per_order": int(s.get("max_per_order", 4)),
            "seller_stock":      int(stock)  # اضافه شدن موجودی
        }]}

        max_retries  = int(s.get("max_retries", 3))
        backoff_base = int(s.get("rate_limit_backoff_base", 15))

        for attempt in range(max_retries):
            try:
                self._sleep(s)
                
                # رفع ارور 405: استفاده از متد PUT به جای POST
                resp = self.client.request(
                    "PUT", url,
                    json_payload=payload,
                    timeout=10, retries=1,
                )
                if resp is None:
                    continue

                if resp.status_code == 429:
                    wait = backoff_base * (2 ** attempt)
                    self.stats["rate_limit_hits"] += 1
                    self.log(f"⏸ 429 — تلاش {attempt+1}/{max_retries} | {wait}s صبر...")
                    if self.stats["rate_limit_hits"] % 8 == 0:
                        self._pause(int(s.get("rate_limit_pause_seconds", 180)), "repeated 429")
                    time.sleep(wait)
                    continue

                if resp.status_code == 401:
                    self.log("⚠️ کوکی منقضی!")
                    self._on_failure("auth_error")
                    return {"success": False, "message": "auth_error"}

                if resp.status_code in (200, 201):
                    body = resp.json()
                    if body.get("status") is False:
                        err = body.get("message", "status=false")
                        if not silent:
                            self.log(f"⚠️ [{variant_id}] رد شد: {err}")
                        self._on_failure(str(err))
                        return {"success": False, "message": str(err)}
                    errors = body.get("data", {}).get("errors", [])
                    if errors:
                        err = str(errors)
                        if not silent:
                            self.log(f"⚠️ [{variant_id}] خطای API: {err}")
                        self._on_failure(err)
                        return {"success": False, "message": err}
                    if not silent:
                        self.log(f"✅ [{variant_id}] با موفقیت آپدیت شد ← {new_price:,} تومان")
                    self.stats["total_updates"] += 1
                    self._on_success()
                    self.last_update_at[str(variant_id)] = time.time()
                    return {"success": True}

                try:
                    err = resp.json().get("message", str(resp.status_code))
                except Exception:
                    err = f"HTTP {resp.status_code}"
                if not silent:
                    self.log(f"⚠️ [{variant_id}] HTTP {resp.status_code}: {err}")
                self._on_failure(err)
                return {"success": False, "message": err}

            except requests.Timeout:
                self.log(f"⏱ [{variant_id}] timeout — تلاش {attempt+1}")
                if attempt < max_retries - 1:
                    time.sleep(5)
            except requests.ConnectionError:
                self.log(f"🔌 [{variant_id}] خطای اتصال اینترنت — تلاش {attempt+1}")
                if attempt < max_retries - 1:
                    time.sleep(8)
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                self._on_failure(str(e))
                return {"success": False, "message": str(e)}

        return {"success": False, "message": "max retries exceeded"}
    
    def discover_price_bounds(self, variant_id: str, reference_price: int,
                               current_price: int) -> dict:
        if not reference_price or reference_price <= 0:
            reference_price = current_price

        self.log(f"🔍 شروع کشف بازه | تنوع {variant_id} | مرجع: {reference_price:,} | جاری: {current_price:,}")

        def test(price: int) -> Optional[bool]:
            if price <= 0:
                return False
            res = self.update_my_price(variant_id, price, silent=True)
            if res.get("dry_run"):
                return True
            if res["success"]:
                time.sleep(1)
                self.update_my_price(variant_id, current_price, silent=True)
                return True
            msg = res.get("message", "").lower()
            if any(x in msg for x in ["auth", "429", "timeout", "connection", "max retries"]):
                return None  
            return False  

        self.log(">> فاز ۱: جستجوی سقف...")
        max_valid = current_price
        lo, hi = 0.0, 0.80  

        for i in range(12):
            mid = (lo + hi) / 2
            price = int(round(reference_price * (1 + mid) / 1000) * 1000)
            if price == max_valid:
                lo = mid
                continue
            self.log(f"  سقف [{i+1}/12] +{round(mid*100,1)}% → {price:,}")
            result = test(price)
            if result is None:
                self.log(f"  ⚠️ نتیجه نامعتبر (شبکه/429) — رد می‌شود")
                continue
            if result:
                max_valid = price
                lo = mid
            else:
                hi = mid
            time.sleep(0.5)

        self.log(">> فاز ۲: جستجوی کف...")
        min_valid = current_price
        lo, hi = 0.0, 0.50  

        for i in range(12):
            mid = (lo + hi) / 2
            price = int(round(reference_price * (1 - mid) / 1000) * 1000)
            if price <= 0 or price == min_valid:
                hi = mid
                continue
            self.log(f"  کف [{i+1}/12] -{round(mid*100,1)}% → {price:,}")
            result = test(price)
            if result is None:
                self.log(f"  ⚠️ نتیجه نامعتبر — رد می‌شود")
                continue
            if result:
                min_valid = price
                lo = mid
            else:
                hi = mid
            time.sleep(0.5)

        self.update_my_price(variant_id, current_price, silent=True)
        self.log(f"🎯 نتیجه: کف={min_valid:,} | سقف={max_valid:,}")
        return {"success": True, "min_price": min_valid, "max_price": max_valid}

    def get_auth_diagnostics(self) -> dict:
        csrf = bool(
            self.session.headers.get("x-csrf-token")
            or self.session.headers.get("X-CSRFToken")
        )
        try:
            resp = self.client.request(
                "GET",
                "https://seller.digikala.com/api/v2/variants?page=1&size=1"
                "&sort=product_variant_id&order=desc",
                timeout=12, retries=1,
            )
            read_status = resp.status_code if resp else 0
        except Exception:
            read_status = 0
        return {
            "workspace_id":              self.workspace_id,
            "cookie_count":              len(self.session.cookies),
            "has_authorization_header":  bool(self.session.headers.get("Authorization")),
            "has_csrf_header":           csrf,
            "variants_read_status":      read_status,
            "is_read_auth_ok":           read_status == 200,
            "is_paused":                 self._is_paused(),
        }

    def get_runtime_metrics(self) -> dict:
        return {
            "workspace_id":   self.workspace_id,
            "stats":          self.stats,
            "is_paused":      self._is_paused(),
        }

    # =========================================================================
    # ─── Main loop (هوشمند شده) ───────────────────────────────────────────────
    # =========================================================================
    def evaluate_and_act_all(self, product_configs: dict,
                              global_step: int = 1000,
                              my_seller_id: int = 0) -> dict:
        
        self.stats["cycles"] += 1
        self.stats["last_cycle_time"] = datetime.now().isoformat()

        if self._is_paused():
            self.log("⏸ این چرخه به دلیل pause ایمنی رد شد.")
            return {"buybox_count": 0, "updated_count": 0, "skipped_count": 0,
                    "rate_limit_hits": self.stats["rate_limit_hits"]}

        s = self._load_settings()
        cooldown = int(s.get("variant_cooldown_seconds", 300))
        default_step = int(s.get("default_step", global_step))

        self.log(f"━━━ چرخه #{self.stats['cycles']} ━━━")

        all_variants = []
        page, total_pages = 1, 1
        while page <= total_pages:
            res = self.get_my_variants(page)
            if not res["success"]:
                break
            total_pages = res["total_pages"]
            all_variants.extend(res["variants"])
            page += 1

        buybox_count = updated_count = skipped_count = 0

        for item in all_variants:
            vid = str(item["variant_id"])

            if vid not in product_configs:
                continue

            conf = product_configs[vid]

            if not conf.get("enabled", True):
                skipped_count += 1
                continue

            min_p = int(conf.get("min_price") or 0)
            max_p = int(conf.get("max_price") or 0)
            if not min_p or not max_p:
                self.log(f"⚠️ [{item['title'][:20]}] کف/سقف تنظیم نشده — رد")
                skipped_count += 1
                continue

            if self._in_cooldown(vid, cooldown):
                skipped_count += 1
                continue

            current = int(item.get("current_price") or 0)
            is_winner = bool(item.get("is_buy_box_winner"))
            product_id = item.get("product_id")
            step = int(conf.get("step", default_step))

            if product_id:
                comp_price, alone, winner_info = self.get_competitor_prices(int(product_id), my_seller_id)
            else:
                comp_price, alone, winner_info = None, False, {}
                self.log(f"⚠️ [{item['title'][:20]}] product_id ندارد — رقبا بررسی نشد")

            time.sleep(0.3)

            if is_winner:
                self.stats["buybox_wins"] += 1
                buybox_count += 1

            target = None
            strategy_name = ""

            # ─── منطق هوشمند (Profit Maximization & Competitor Weighting) ─────
            
            # حالت 1: ما برنده هستیم -> طمع برای سود بیشتر
            if is_winner:
                strategy_name = "Profit-Max (افزایش)"
                if alone or not comp_price:
                    self.log(f"👑 [{item['title'][:20]}] شما تنها فروشنده هستید! صعود به سقف...")
                    target = max_p
                else:
                    # قیمت رو می‌بریم 10 هزار تومن زیر قیمت نفر دوم
                    target = comp_price - step
                    if target > max_p:
                        target = max_p
                    if target <= current:
                        target = None # نیازی به تغییر نیست
            
            # حالت 2: ما بازنده هستیم -> حمله به بای‌باکس
            else:
                strategy_name = "Aggressive (کاهش)"
                if not winner_info:
                    target = current # دیتایی از رقیب نیست، کاری نمی‌کنیم
                else:
                    w_price = winner_info.get("price", 0)
                    w_votes = winner_info.get("votes", 0)
                    my_votes = 460 # می‌تواند در آینده داینامیک شود
                    
                    # فرمول غول‌کُش (وزن رقیب سنگین)
                    if w_votes > 10000 and my_votes < 1000:
                        drop_amount = int(w_price * 0.012) # 1.2 درصد کاهش
                        target = w_price - drop_amount
                        target = (target // 10000) * 10000 
                        self.log(f"🥊 غلبه بر غول: رقابت با رقیب سنگین‌وزن")
                    else:
                        target = w_price - step

            # ─── اعمال گاردها ──────────────────────────────────────────────
            if target is None:
                skipped_count += 1
                continue

            # گارد ضرر و سقف مجاز
            target = max(min_p, min(max_p, target))
            target = int(round(target / 1000) * 1000)

            # گارد کش (Cache Guard) - اگر قیمت هدف با سایت یکی است، منتظر بمان
            if target == current:
                self.log(f"⏳ [Cache Guard] قیمت هدف ({target:,}) با قیمت فعلی یکی است. انتظار...")
                skipped_count += 1
                continue

            comp_str = f"{comp_price:,}" if comp_price else "—"
            self.log(
                f"🎯 [{item['title'][:20]}] "
                f"{current:,} → {target:,} | استراتژی: {strategy_name}"
            )
            
            self.update_my_price(vid, target)
            updated_count += 1

        self.log(
            f"━━━ پایان | BuyBox:{buybox_count} "
            f"آپدیت:{updated_count} رد:{skipped_count} ━━━"
        )
        return {
            "buybox_count":    buybox_count,
            "updated_count":   updated_count,
            "skipped_count":   skipped_count,
            "rate_limit_hits": self.stats["rate_limit_hits"],
        }