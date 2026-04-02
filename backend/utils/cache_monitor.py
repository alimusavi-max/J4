"""
backend/utils/cache_monitor.py

پایش تغییر کش دیجی‌کالا بعد از آپدیت قیمت.
نسخه ۵.۱ — رفع NameError برای W_PRICE/W_SELLER/W_LEAD
تغییرات: افزایش زمان پایش به ۴۰ دقیقه و چک کردن هر ۱ دقیقه
"""
from __future__ import annotations

import time
import threading
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

# ─── FIX: import ضرایب از strategies به جای تعریف محلی ──────────────────────
from utils.strategies import W_PRICE, W_SELLER, W_LEAD

BASE_DIR    = Path(__file__).resolve().parent.parent
MONITOR_LOG = BASE_DIR / "cache_monitor_log.json"

POLL_INTERVAL_SEC = 60    # <--- تغییر یافت به ۶۰ ثانیه (۱ دقیقه)
MAX_WAIT_SEC      = 2400  # <--- تغییر یافت به ۲۴۰۰ ثانیه (۴۰ دقیقه)
SCORE_CHANGE_EPS  = 0.5
PRICE_CHANGE_EPS  = 5_000


@dataclass
class CacheSnapshot:
    variant_id:    int
    product_id:    int
    price:         int
    buy_box_score: Optional[float]
    is_winner:     bool
    captured_at:   float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "variant_id":    self.variant_id,
            "product_id":    self.product_id,
            "price":         self.price,
            "buy_box_score": self.buy_box_score,
            "is_winner":     self.is_winner,
            "captured_at":   self.captured_at,
        }


@dataclass
class CacheFlushEvent:
    variant_id:    int
    product_id:    int
    before_price:  int
    after_price:   int
    before_score:  Optional[float]
    after_score:   Optional[float]
    before_winner: bool
    after_winner:  bool
    wait_seconds:  float
    flushed_at:    str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        return {
            "variant_id":    self.variant_id,
            "product_id":    self.product_id,
            "before_price":  self.before_price,
            "after_price":   self.after_price,
            "before_score":  self.before_score,
            "after_score":   self.after_score,
            "before_winner": self.before_winner,
            "after_winner":  self.after_winner,
            "wait_seconds":  round(self.wait_seconds, 1),
            "flushed_at":    self.flushed_at,
        }


class CacheMonitor:
    def __init__(self, log_callback: Optional[Callable] = None):
        self.log_cb   = log_callback or print
        self._active:  Dict[int, threading.Thread] = {}
        self._history: List[Dict]                  = []
        self._lock     = threading.Lock()
        self._load_history()

        self.public_session = requests.Session()
        self.public_session.headers.update({
            "User-Agent":     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":         "application/json, text/plain, */*",
            "x-web-client":   "desktop",
            "x-web-client-id":"web",
        })

    def _load_history(self) -> None:
        if MONITOR_LOG.exists():
            try:
                with MONITOR_LOG.open("r", encoding="utf-8") as f:
                    self._history = json.load(f)
            except Exception:
                self._history = []

    def _save_history(self) -> None:
        MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with MONITOR_LOG.open("w", encoding="utf-8") as f:
            json.dump(self._history[-500:], f, ensure_ascii=False, indent=2)

    def _log(self, msg: str) -> None:
        full = f"[CacheMon {datetime.now().strftime('%H:%M:%S')}] {msg}"
        print(full, flush=True)
        self.log_cb(full)

    def fetch_snapshot(
        self,
        product_id:   int,
        variant_id:   int,
        my_seller_id: int,
    ) -> Optional[CacheSnapshot]:
        url = f"https://api.digikala.com/v2/product/{product_id}/"
        try:
            resp = self.public_session.get(url, timeout=10)
            if resp.status_code != 200:
                return None

            data     = resp.json()
            variants = (data.get("data", {})
                           .get("product", {})
                           .get("variants", []))

            my_var = next(
                (v for v in variants if int(v.get("id", 0)) == int(variant_id)),
                None,
            )
            if not my_var:
                my_var = next(
                    (v for v in variants
                     if int((v.get("seller") or {}).get("id") or 0) == int(my_seller_id)),
                    None,
                )
            if not my_var:
                return None

            price = int((my_var.get("price") or {}).get("selling_price") or 0)

            marketable = [v for v in variants if v.get("status") == "marketable"]
            score      = self._estimate_score(my_var, marketable)
            is_winner  = self._detect_winner(my_var, marketable)

            return CacheSnapshot(
                variant_id    = variant_id,
                product_id    = product_id,
                price         = price,
                buy_box_score = score,
                is_winner     = is_winner,
            )

        except Exception as e:
            self._log(f"⚠️ fetch_snapshot خطا: {e}")
            return None

    def _estimate_score(self, my_var: Dict, marketable: List[Dict]) -> float:
        if not marketable:
            return 50.0

        sorted_by_price = sorted(
            marketable,
            key=lambda x: int((x.get("price") or {}).get("selling_price") or 0),
        )

        my_price = int((my_var.get("price") or {}).get("selling_price") or 0)
        my_rate  = float((my_var.get("seller") or {}).get("rating", {}).get("total_rate") or 0)

        min_price   = int((sorted_by_price[0].get("price") or {}).get("selling_price") or 1)
        max_price   = int((sorted_by_price[-1].get("price") or {}).get("selling_price") or 1)
        price_range = max(max_price - min_price, 1)

        price_score  = (1 - (my_price - min_price) / price_range) * 100
        seller_score = my_rate
        combined     = price_score * W_PRICE + seller_score * W_SELLER
        normalized   = 50.0 + combined * 0.5
        return round(min(99.9, max(50.0, normalized)), 2)

    def _detect_winner(self, my_var: Dict, marketable: List[Dict]) -> bool:
        if not marketable:
            return True
        sorted_vars  = sorted(
            marketable,
            key=lambda x: int((x.get("price") or {}).get("selling_price") or 0),
        )
        cheapest_id  = int((sorted_vars[0].get("seller") or {}).get("id") or 0)
        my_seller_id = int((my_var.get("seller") or {}).get("id") or 0)
        return cheapest_id == my_seller_id

    def watch(
        self,
        variant_id:      int,
        product_id:      int,
        my_seller_id:    int,
        snapshot_before: CacheSnapshot,
        on_flush:        Callable[[CacheFlushEvent], None],
        poll_interval:   int = POLL_INTERVAL_SEC,
        max_wait:        int = MAX_WAIT_SEC,
    ) -> None:
        with self._lock:
            if variant_id in self._active:
                self._log(f"⏭ watch قبلی برای {variant_id} جایگزین می‌شود")

        t = threading.Thread(
            target=self._watch_loop,
            args=(variant_id, product_id, my_seller_id, snapshot_before, on_flush, poll_interval, max_wait),
            daemon=True,
            name=f"cache_watch_{variant_id}",
        )
        with self._lock:
            self._active[variant_id] = t
        t.start()
        self._log(f"👁 پایش کش | تنوع {variant_id} | قیمت قبل: {snapshot_before.price:,}")

    def _watch_loop(
        self,
        variant_id:   int,
        product_id:   int,
        my_seller_id: int,
        before:       CacheSnapshot,
        on_flush:     Callable[[CacheFlushEvent], None],
        poll_interval: int,
        max_wait:     int,
    ) -> None:
        start_time = time.time()
        checks     = 0
        try:
            while (time.time() - start_time) < max_wait:
                time.sleep(poll_interval)
                checks  += 1
                elapsed  = time.time() - start_time

                after = self.fetch_snapshot(product_id, variant_id, my_seller_id)
                if after is None:
                    continue

                price_changed = abs(after.price - before.price) >= PRICE_CHANGE_EPS
                score_before  = before.buy_box_score or 0.0
                score_after   = after.buy_box_score  or 0.0
                score_changed = abs(score_after - score_before) >= SCORE_CHANGE_EPS

                if price_changed or score_changed:
                    event = CacheFlushEvent(
                        variant_id    = variant_id,
                        product_id    = product_id,
                        before_price  = before.price,
                        after_price   = after.price,
                        before_score  = before.buy_box_score,
                        after_score   = after.buy_box_score,
                        before_winner = before.is_winner,
                        after_winner  = after.is_winner,
                        wait_seconds  = elapsed,
                    )
                    with self._lock:
                        self._history.append(event.to_dict())
                        self._save_history()
                    self._log(
                        f"✅ [{variant_id}] کش flush | {elapsed:.0f}s | "
                        f"قیمت: {before.price:,}→{after.price:,} | "
                        f"برنده: {before.is_winner}→{after.is_winner}"
                    )
                    try:
                        on_flush(event)
                    except Exception as e:
                        self._log(f"❌ on_flush خطا: {e}")
                    return

                self._log(
                    f"⏳ [{variant_id}] چک #{checks} | {elapsed:.0f}s | "
                    f"قیمت: {after.price:,} | امتیاز: {score_after:.1f}"
                )

            self._log(f"⏰ [{variant_id}] timeout بعد از {max_wait}s")
        finally:
            with self._lock:
                self._active.pop(variant_id, None)

    def get_history(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            return self._history[-limit:]

    def get_active_watches(self) -> List[int]:
        with self._lock:
            return list(self._active.keys())

    def get_avg_flush_time(self) -> Optional[float]:
        with self._lock:
            if not self._history:
                return None
            times = [h["wait_seconds"] for h in self._history if "wait_seconds" in h]
            return round(sum(times) / len(times), 1) if times else None