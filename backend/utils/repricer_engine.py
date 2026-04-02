"""
backend/utils/repricer_engine.py

موتور اصلی ربات قیمت‌گذاری — نسخه ۵.۲
تغییرات: تنظیمات پیش‌فرض پایش کش به ۶۰ ثانیه اینتروال و ۲۴۰۰ ثانیه (۴۰ دقیقه) مکس‌وِیت آپدیت شد
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
from utils.strategies import (
    StrategyInput, get_strategy,
    AdaptiveMemory, BuyBoxScorePredictor, ScenarioEngine,
    DEFAULT_STEP,
)
from utils.cache_monitor import CacheMonitor, CacheSnapshot, CacheFlushEvent

BASE_DIR      = Path(__file__).resolve().parent.parent
SESSIONS_DIR  = BASE_DIR / "panel_sessions"
SETTINGS_FILE = BASE_DIR / "repricer_settings.json"

DEFAULT_SETTINGS = {
    "lead_time":                2,
    "shipping_type":            "seller",
    "max_per_order":            4,
    "request_delay_min":        3.0,
    "request_delay_max":        6.0,
    "rate_limit_backoff_base":  15,
    "max_retries":              3,        # ← مقدار معقول (نه 999)
    "default_strategy":         "adaptive_sniper",
    "default_step":             20_000,
    "dry_run":                  False,
    "variant_cooldown_seconds": 300,
    "notify_webhook_url":       "",
    "rate_limit_pause_seconds": 180,
    "max_consecutive_failures": 10,
    "my_seller_id":             0,
    "my_seller_rate":           85.0,
    "enable_cache_monitor":     True,
    "cache_poll_interval":      60,      # <--- آپدیت شد به ۶۰ ثانیه
    "cache_max_wait":           2400,    # <--- آپدیت شد به ۴۰ دقیقه
    "credit_increase_percentage": 8.1,   
}


class DigikalaSellerClient:
    """HTTP client با retry/backoff"""
    RETRYABLE = {429, 502, 503, 504}

    def __init__(self, session: requests.Session, log: Callable):
        self.session = session
        self.log     = log

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
            "total_updates":        0,
            "buybox_wins":          0,
            "cycles":               0,
            "last_cycle_time":      None,
            "rate_limit_hits":      0,
            "failed_updates":       0,
            "last_error":           "",
            "consecutive_failures": 0,
            "paused_until":         0.0,
            "cache_flushes_seen":   0,
        }
        self.last_update_at: dict[str, float] = {}

        self.memory          = AdaptiveMemory()
        self.predictor       = BuyBoxScorePredictor(self.memory)
        self.scenario_engine = ScenarioEngine(self.predictor, self.memory)
        self.cache_monitor   = CacheMonitor(log_callback=self.log)

        # ─── Seller session ──────────────────────────────────────────────────
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":       "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin":       "https://seller.digikala.com",
            "Referer":      "https://seller.digikala.com/pwa/variant-management",
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

        # ─── Public session ──────────────────────────────────────────────────
        self.public_session = requests.Session()
        self.public_session.headers.update({
            "User-Agent":     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":         "application/json, text/plain, */*",
            "x-web-client":   "desktop",
            "x-web-client-id":"web",
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
                    loaded = json.load(f)
                    if loaded.get("max_retries", 0) > 10:
                        loaded["max_retries"] = 3
                        self.log("⚠️ max_retries به ۳ reset شد (مقدار قبلی خیلی زیاد بود)")
                    return {**DEFAULT_SETTINGS, **loaded}
            except Exception:
                pass
        return DEFAULT_SETTINGS.copy()

    def _load_cookies(self):
        cm     = ManualCookieManager(SESSIONS_DIR)
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
        self.stats["failed_updates"]       += 1
        self.stats["consecutive_failures"] += 1
        self.stats["last_error"]            = reason
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
    # GET: رقبا
    # =========================================================================
    def get_competitor_prices(
        self,
        product_id:    int,
        my_seller_id:  int,
        my_variant_id: int,
    ) -> Tuple[Optional[int], bool, Dict[str, Any]]:
        url = f"https://api.digikala.com/v2/product/{product_id}/"
        try:
            resp = self.public_session.get(url, timeout=10)
            if resp.status_code != 200:
                return None, False, {}

            data         = resp.json()
            product_data = data.get("data", {}).get("product", {})
            variants     = product_data.get("variants", [])

            my_variant = next(
                (v for v in variants if int(v.get("id", 0)) == int(my_variant_id)), None
            )
            if not my_variant:
                return None, False, {}

            my_color_id    = (my_variant.get("color") or {}).get("id")
            my_warranty_id = (my_variant.get("warranty") or {}).get("id")

            def _same_family(v: Dict) -> bool:
                return (
                    (v.get("color") or {}).get("id")    == my_color_id and
                    (v.get("warranty") or {}).get("id") == my_warranty_id
                )

            same_family   = [v for v in variants if _same_family(v)]
            marketable    = [v for v in same_family if v.get("status") == "marketable"]
            sorted_market = sorted(
                marketable,
                key=lambda x: int((x.get("price") or {}).get("selling_price") or 0),
            )

            winner_info: Dict[str, Any] = {}
            if sorted_market:
                wv         = sorted_market[0]
                ws         = wv.get("seller") or {}
                statistics = wv.get("statistics") or {}
                winner_info = {
                    "seller_id":   ws.get("id"),
                    "seller_rate": float((ws.get("rating") or {}).get("total_rate") or 0),
                    "lead_time":   int(wv.get("lead_time") or 2),
                    "price":       int((wv.get("price") or {}).get("selling_price") or 0),
                    "item_votes":  int(statistics.get("total_count") or 0),
                    "variant_id":  wv.get("id"),
                }

            prices = [
                int((v.get("price") or {}).get("selling_price") or 0)
                for v in marketable
                if int((v.get("seller") or {}).get("id") or 0) not in (0, my_seller_id)
                and int((v.get("price") or {}).get("selling_price") or 0) > 0
            ]

            if not prices:
                return None, True, winner_info

            return min(prices), False, winner_info

        except Exception as e:
            self.log(f"❌ get_competitor_prices product={product_id}: {e}")
            return None, False, {}

    # =========================================================================
    # GET: تنوع‌های من
    # =========================================================================
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
                self.log("⚠️ کوکی منقضی! لطفاً کوکی را تجدید کنید.")
                return {"success": False, "variants": [], "total_pages": 1, "auth_error": True}
            if resp.status_code == 429:
                self.log("⏸ 429 هنگام دریافت تنوع‌ها — ۲۰ ثانیه صبر...")
                time.sleep(20)
                return {"success": False, "variants": [], "total_pages": 1}
            if resp.status_code == 200:
                data        = resp.json()
                items       = data.get("data", {}).get("items", [])
                total_pages = data.get("data", {}).get("pager", {}).get("total_pages", 1)
                variants    = []
                for item in items:
                    if item.get("active") and item.get("marketplace_seller_stock", 0) > 0:
                        variants.append({
                            "variant_id":              item.get("product_variant_id"),
                            "product_id":              item.get("product_id"),
                            "title":                   item.get("product_title"),
                            "is_buy_box_winner":       item.get("is_buy_box_winner"),
                            "current_price":           item.get("price_sale"),
                            "reference_price":         item.get("price_list"),
                            "buy_box_price":           item.get("buy_box_price"),
                            "buy_box_score":           item.get("buy_box_score"),
                            "stock":                   item.get("marketplace_seller_stock", 0),
                            "seller_stock":            item.get("seller_stock", 0),
                            "credit_increase_percentage": item.get("credit_increase_percentage", 8.1),
                        })
                return {"success": True, "variants": variants, "total_pages": total_pages}
            return {"success": False, "variants": [], "total_pages": 1}
        except Exception as e:
            self.log(f"❌ get_my_variants: {e}")
            return {"success": False, "variants": [], "total_pages": 1}

    # =========================================================================
    # PUT: آپدیت قیمت
    # =========================================================================
    def update_my_price(
        self,
        variant_id:   str,
        new_price:    int,
        stock:        int = 1,
        silent:       bool = False,
        product_id:   Optional[int] = None,
        my_seller_id: int = 0,
        credit_increase_percentage: float = 8.1,
    ) -> dict:
        url = "https://seller.digikala.com/api/v2/variants/bulk"
        s   = self._load_settings()

        if bool(s.get("dry_run", False)):
            self.log(f"🧪 [DRY-RUN] تنوع {variant_id} → {new_price:,}")
            return {"success": True, "dry_run": True}

        # snapshot قبل از ارسال
        snapshot_before: Optional[CacheSnapshot] = None
        if product_id and my_seller_id and s.get("enable_cache_monitor", True):
            snapshot_before = self.cache_monitor.fetch_snapshot(
                product_id   = product_id,
                variant_id   = int(variant_id),
                my_seller_id = my_seller_id,
            )

        payload = {"variants": [{
            "variant_id":                 int(variant_id),
            "selling_price":              int(new_price),
            "shipping_type":              s.get("shipping_type", "seller"),
            "seller_lead_time":           int(s.get("lead_time", 2)),
            "maximum_per_order":          int(s.get("max_per_order", 4)),
            "seller_stock":               int(stock),
            "credit_increase_percentage": float(
                s.get("credit_increase_percentage", credit_increase_percentage)
            ),
        }]}

        max_retries  = int(s.get("max_retries", 3))
        backoff_base = int(s.get("rate_limit_backoff_base", 15))

        for attempt in range(max_retries):
            try:
                self._sleep(s)
                resp = self.client.request("PUT", url, json_payload=payload, timeout=10, retries=1)
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
                    body   = resp.json()
                    errors = body.get("data", {}).get("errors", [])
                    if body.get("status") is False or errors:
                        err = body.get("message") or str(errors)
                        if not silent:
                            self.log(f"⚠️ [{variant_id}] رد شد: {err}")
                        self._on_failure(str(err))
                        return {"success": False, "message": str(err)}

                    confirmed = (
                        body.get("data", {})
                            .get("successful_updates", [{}])[0]
                            .get("price_sale", new_price)
                    )
                    if not silent:
                        self.log(
                            f"✅ [{variant_id}] ← {new_price:,} ریال"
                            + (f" (تایید: {confirmed:,})" if confirmed != new_price else "")
                        )

                    self.stats["total_updates"]      += 1
                    self._on_success()
                    self.last_update_at[str(variant_id)] = time.time()

                    if snapshot_before and product_id and my_seller_id:
                        self.cache_monitor.watch(
                            variant_id      = int(variant_id),
                            product_id      = product_id,
                            my_seller_id    = my_seller_id,
                            snapshot_before = snapshot_before,
                            on_flush        = lambda ev: self._on_cache_flush(ev, variant_id),
                            poll_interval   = int(s.get("cache_poll_interval", 60)), # آپدیت شد
                            max_wait        = int(s.get("cache_max_wait", 2400)),    # آپدیت شد
                        )

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
                self.log(f"🔌 [{variant_id}] خطای اتصال — تلاش {attempt+1}")
                if attempt < max_retries - 1:
                    time.sleep(8)
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                self._on_failure(str(e))
                return {"success": False, "message": str(e)}

        return {"success": False, "message": "max retries exceeded"}

    # =========================================================================
    # Callback: وقتی کش flush شد
    # =========================================================================
    def _on_cache_flush(self, event: CacheFlushEvent, variant_id: str) -> None:
        from utils.strategies import _ceiling_cache
        self.stats["cache_flushes_seen"] += 1

        if event.after_score and event.before_score:
            self.predictor.calibrate(
                my_price         = event.after_price,
                comp_price       = event.before_price,
                observed_score   = event.after_score,
                my_seller_rate   = 85.0,
                comp_seller_rate = 82.0,
            )
            self.log(
                f"🎯 [{variant_id}] کالیبراسیون | "
                f"قیمت {event.after_price:,} → امتیاز {event.after_score:.1f} | "
                f"برنده: {event.after_winner}"
            )

        gap = max(0, event.before_price - event.after_price)
        self.memory.record_result(
            competitor_seller_id = 0,
            gap                  = gap,
            won                  = event.after_winner,
            my_score             = event.after_score,
            comp_score           = None,
        )

        if event.after_winner:
            self.log(f"🏆 [{variant_id}] بعد از flush: برنده! امتیاز={event.after_score or 0:.1f}")
        else:
            self.log(f"📉 [{variant_id}] بعد از flush: بازنده | امتیاز={event.after_score or 0:.1f}")
            if event.after_price > event.before_price:
                _ceiling_cache.invalidate(variant_id)
                self.log(f"🔄 [{variant_id}] ceiling cache invalidate — قیمت از سقف رد شد")

    # =========================================================================
    # discover_price_bounds
    # =========================================================================
    def discover_price_bounds(self, variant_id: str, reference_price: int,
                               current_price: int) -> dict:
        if not reference_price or reference_price <= 0:
            reference_price = current_price

        self.log(f"🔍 کشف بازه | {variant_id} | مرجع: {reference_price:,} | جاری: {current_price:,}")

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
        lo, hi    = 0.0, 0.80

        for i in range(12):
            mid   = (lo + hi) / 2
            price = int(round(reference_price * (1 + mid) / DEFAULT_STEP) * DEFAULT_STEP)
            if price == max_valid:
                lo = mid
                continue
            self.log(f"  سقف [{i+1}/12] +{round(mid*100,1)}% → {price:,}")
            result = test(price)
            if result is None:
                continue
            if result:
                max_valid = price
                lo = mid
            else:
                hi = mid
            time.sleep(0.5)

        self.log(">> فاز ۲: جستجوی کف...")
        min_valid = current_price
        lo, hi    = 0.0, 0.50

        for i in range(12):
            mid   = (lo + hi) / 2
            price = int(round(reference_price * (1 - mid) / DEFAULT_STEP) * DEFAULT_STEP)
            if price <= 0 or price == min_valid:
                hi = mid
                continue
            self.log(f"  کف [{i+1}/12] -{round(mid*100,1)}% → {price:,}")
            result = test(price)
            if result is None:
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

    # =========================================================================
    # Diagnostics + metrics
    # =========================================================================
    def get_auth_diagnostics(self) -> dict:
        csrf = bool(
            self.session.headers.get("x-csrf-token")
            or self.session.headers.get("X-CSRFToken")
        )
        try:
            resp = self.client.request(
                "GET",
                "https://seller.digikala.com/api/v2/variants?page=1&size=1&sort=product_variant_id&order=desc",
                timeout=12, retries=1,
            )
            read_status = resp.status_code if resp else 0
        except Exception:
            read_status = 0

        return {
            "workspace_id":             self.workspace_id,
            "cookie_count":             len(self.session.cookies),
            "has_authorization_header": bool(self.session.headers.get("Authorization")),
            "has_csrf_header":          csrf,
            "variants_read_status":     read_status,
            "is_read_auth_ok":          read_status == 200,
            "is_paused":                self._is_paused(),
            "cache_monitor": {
                "active_watches":     self.cache_monitor.get_active_watches(),
                "avg_flush_time_sec": self.cache_monitor.get_avg_flush_time(),
                "total_flushes":      self.stats["cache_flushes_seen"],
            },
        }

    def get_runtime_metrics(self) -> dict:
        return {
            "workspace_id":          self.workspace_id,
            "stats":                 self.stats,
            "is_paused":             self._is_paused(),
            "cache_monitor_history": self.cache_monitor.get_history(10),
        }

    # =========================================================================
    # Main loop
    # =========================================================================
    def evaluate_and_act_all(
        self,
        product_configs: dict,
        global_step:     int = DEFAULT_STEP,
        my_seller_id:    int = 0,
    ) -> dict:

        self.stats["cycles"]         += 1
        self.stats["last_cycle_time"] = datetime.now().isoformat()

        if self._is_paused():
            self.log("⏸ این چرخه به دلیل pause ایمنی رد شد.")
            return {"buybox_count": 0, "updated_count": 0, "skipped_count": 0,
                    "rate_limit_hits": self.stats["rate_limit_hits"]}

        s            = self._load_settings()
        cooldown     = int(s.get("variant_cooldown_seconds", 300))
        default_step = int(s.get("default_step", DEFAULT_STEP))
        my_seller_rt = float(s.get("my_seller_rate", 85.0))
        my_lead      = int(s.get("lead_time", 2))

        def _probe_price(vid: str, price: int) -> bool:
            res = self.update_my_price(variant_id=vid, new_price=price, stock=1, silent=True)
            return res.get("success", False)

        self.scenario_engine.price_probe_fn = _probe_price
        self.log(f"━━━ چرخه #{self.stats['cycles']} ━━━")

        all_variants: list = []
        page, total_pages  = 1, 1
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

            current    = int(item.get("current_price") or 0)
            is_winner  = bool(item.get("is_buy_box_winner"))
            product_id = item.get("product_id") or conf.get("product_id")
            step       = int(conf.get("step", default_step))
            credit_pct = float(item.get("credit_increase_percentage") or
                               s.get("credit_increase_percentage", 8.1))

            if product_id:
                comp_price, alone, winner_info = self.get_competitor_prices(
                    int(product_id), my_seller_id, int(vid),
                )
            else:
                comp_price, alone, winner_info = None, False, {}
                self.log(f"⚠️ [{item['title'][:20]}] product_id ندارد")

            time.sleep(0.3)

            if is_winner:
                self.stats["buybox_wins"] += 1
                buybox_count += 1

            strategy_input = StrategyInput(
                competitor_price  = int(comp_price or 0),
                current_price     = current,
                min_price         = min_p,
                max_price         = max_p,
                step              = step,
                is_buy_box_winner = is_winner,
                alone_in_market   = alone,
                winner_info       = winner_info,
                my_seller_rate    = my_seller_rt,
                my_lead_time      = my_lead,
                buy_box_score     = item.get("buy_box_score"),
                reference_price   = int(item.get("reference_price") or 0),
                variant_id        = vid,
            )

            strategy = get_strategy(str(conf.get("strategy", "adaptive_sniper")))
            result   = strategy.decide_with_details(strategy_input)

            comp_str = f"رقیب: {comp_price:,}" if comp_price else "تنها در بازار"
            self.log(
                f"🎯 [{item['title'][:20]}] "
                f"{comp_str} | "
                f"سناریو: {result.scenario} | "
                f"{current:,}→{result.target_price:,} | "
                f"conf={result.confidence:.0%}"
            )

            if result.scenario in ("no_change", "hold", "greed_blocked", "alone_hold", "greed_ceiling"):
                skipped_count += 1
                continue

            target = max(min_p, min(max_p, result.target_price))
            target = int(round(target / DEFAULT_STEP) * DEFAULT_STEP)

            if target == current:
                skipped_count += 1
                continue

            self.update_my_price(
                variant_id                  = vid,
                new_price                   = target,
                stock                       = int(item.get("seller_stock") or item.get("stock") or 1),
                product_id                  = int(product_id) if product_id else None,
                my_seller_id                = my_seller_id,
                credit_increase_percentage  = credit_pct,
            )

            winner_seller_id = int((winner_info or {}).get("seller_id") or 0)
            if winner_seller_id:
                gap = max(0, int((winner_info or {}).get("price", 0)) - int(target))
                self.memory.record_result(
                    competitor_seller_id = winner_seller_id,
                    gap                  = gap,
                    won                  = not is_winner,
                    my_score             = result.predicted_score,
                )

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