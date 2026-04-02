"""
backend/utils/strategies.py

BuyBox Score Engine — پیش‌بینی امتیاز بای‌باکس + سناریوهای هوشمند
نسخه ۶.۰ — Aggressive Greed Loop (طمع دائمی با گام‌های کاهشی ۲۰->۱۰->۵)
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
LEARNING_MEMORY_FILE = BASE_DIR / "learning_memory.json"
CEILING_CACHE_FILE   = BASE_DIR / "price_ceiling_cache.json"

# ─── ثابت‌های امتیازدهی ───────────────────────────────────────────────────
# تغییرات جدید کاربر: حد طمع به 50 کاهش یافت تا همیشه در صورت برد، بالا برود
W_PRICE  = 0.72   
W_SELLER = 0.20   
W_LEAD   = 0.08   

GREED_THRESHOLD      = 50.0   # هر امتیازی بالای 50 اجازه طمع می‌دهد
SAFE_ZONE_MIN        = 50.0   
WIN_THRESHOLD        = 80.0   
RETREAT_THRESHOLD    = 60.0   
DEFAULT_STEP         = 20_000 # گام اولیه طمع

CEILING_CACHE_TTL_SEC  = 3600   
CEILING_PROBE_MAX_ITER = 10     


# ─── مدل داده ─────────────────────────────────────────────────────────────────
@dataclass
class StrategyInput:
    competitor_price:  int
    current_price:     int
    min_price:         int
    max_price:         int
    step:              int
    is_buy_box_winner: bool
    alone_in_market:   bool
    winner_info:       Optional[Dict[str, Any]] = None
    my_seller_rate:    float = 85.0
    my_seller_votes:   int   = 0
    my_lead_time:      int   = 2
    buy_box_score:     Optional[float] = None   
    reference_price:   int   = 0                
    variant_id:        str   = "0"              


@dataclass
class ScenarioResult:
    target_price:   int
    predicted_score: float
    scenario:       str   
    reason:         str
    confidence:     float  


# ─── حافظه تطبیقی ─────────────────────────────────────────────────────────────
class AdaptiveMemory:
    MAX_OBS = 30  

    def __init__(self, path: Path = LEARNING_MEMORY_FILE) -> None:
        self.path   = path
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._cache = data
            except Exception:
                self._cache = {}
        self._loaded = True

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    def get_state(self, competitor_seller_id: int) -> Dict[str, Any]:
        self._load()
        return self._cache.get(str(competitor_seller_id), {}).copy()

    def record_result(
        self,
        competitor_seller_id: int,
        gap: int,
        won: bool,
        my_score: Optional[float] = None,
        comp_score: Optional[float] = None,
    ) -> None:
        self._load()
        sid = str(competitor_seller_id)
        entry = self._cache.get(sid, {
            "observations": [],
            "best_gap": 0,
            "win_rate": 0.0,
            "last_gap": 0,
            "last_result": "loss",
        })

        obs = {
            "gap":       int(gap), # در نسخه جدید گپ منفی هم برای ذخیره معتبر است
            "won":       won,
            "my_score":  my_score,
            "comp_score": comp_score,
        }
        observations: List[Dict] = entry.get("observations", [])
        observations.append(obs)
        if len(observations) > self.MAX_OBS:
            observations = observations[-self.MAX_OBS:]

        wins  = [o for o in observations if o["won"]]
        total = len(observations)
        win_rate = len(wins) / total if total else 0.0

        best_gap = min((o["gap"] for o in wins), default=gap) if wins else gap

        entry.update({
            "observations": observations,
            "best_gap":     int(best_gap),
            "win_rate":     round(win_rate, 3),
            "last_gap":     int(gap),
            "last_result":  "win" if won else "loss",
        })
        self._cache[sid] = entry
        self._save()

    def get_optimal_gap(self, competitor_seller_id: int, default_step: int) -> Tuple[int, float]:
        self._load()
        state = self._cache.get(str(competitor_seller_id), {})
        observations = state.get("observations", [])

        if len(observations) < 3:
            return default_step, 0.2  

        wins = [o for o in observations if o["won"]]
        if not wins:
            last_gap = state.get("last_gap", default_step)
            return max(default_step, last_gap - default_step // 2), 0.3

        best_gap  = min(o["gap"] for o in wins)
        win_rate  = len(wins) / len(observations)
        confidence = min(0.95, win_rate * (len(observations) / 15))

        recent = observations[-5:]
        recent_win_rate = sum(1 for o in recent if o["won"]) / len(recent)
        if recent_win_rate == 1.0 and best_gap > default_step:
            explore_gap = max(default_step // 2, best_gap - default_step)
            return explore_gap, confidence * 0.8  

        return best_gap, confidence


# ─── BuyBox Score Predictor ───────────────────────────────────────────────────
class BuyBoxScorePredictor:
    def __init__(self, memory: AdaptiveMemory):
        self.memory = memory
        self._price_sensitivity = 1.0 / 500_000   

    def predict_score(
        self,
        my_price:      int,
        comp_price:    int,
        my_seller_rate: float = 85.0,
        comp_seller_rate: float = 82.0,
        my_lead_time:  int   = 2,
        comp_lead_time: int  = 2,
        base_score:    float = 88.0,
    ) -> float:
        price_delta = (comp_price - my_price) * self._price_sensitivity
        price_component = price_delta * 100 * W_PRICE
        seller_delta = (my_seller_rate - comp_seller_rate) / 100
        seller_component = seller_delta * 100 * W_SELLER
        lead_delta = (comp_lead_time - my_lead_time)
        lead_component = lead_delta * 5 * W_LEAD

        score = base_score + price_component + seller_component + lead_component
        return max(0.0, min(100.0, round(score, 2)))

    def find_price_for_score(
        self,
        target_score:  float,
        comp_price:    int,
        my_seller_rate: float = 85.0,
        comp_seller_rate: float = 82.0,
        my_lead_time:  int   = 2,
        comp_lead_time: int  = 2,
        min_price:     int   = 0,
        max_price:     int   = 0,
        base_score:    float = 88.0,
    ) -> int:
        seller_delta   = (my_seller_rate - comp_seller_rate) / 100
        seller_comp    = seller_delta * 100 * W_SELLER
        lead_delta     = (comp_lead_time - my_lead_time)
        lead_comp      = lead_delta * 5 * W_LEAD

        needed_price_comp = target_score - base_score - seller_comp - lead_comp
        divisor = self._price_sensitivity * 100 * W_PRICE
        if abs(divisor) < 1e-9:
            return comp_price

        my_price = comp_price - (needed_price_comp / divisor)
        my_price = int(round(my_price / DEFAULT_STEP) * DEFAULT_STEP)

        if max_price > 0:
            my_price = min(my_price, max_price)
        if min_price > 0:
            my_price = max(my_price, min_price)

        return my_price

    def calibrate(
        self,
        my_price: int,
        comp_price: int,
        observed_score: float,
        my_seller_rate: float = 85.0,
        comp_seller_rate: float = 82.0,
    ) -> None:
        price_diff = comp_price - my_price
        if abs(price_diff) < 1000:
            return  

        seller_delta = (my_seller_rate - comp_seller_rate) / 100
        seller_comp  = seller_delta * 100 * W_SELLER

        base = 88.0
        numerator = observed_score - base - seller_comp
        denominator = price_diff * 100 * W_PRICE

        if abs(denominator) < 1e-9:
            return

        new_sensitivity = numerator / denominator
        self._price_sensitivity = 0.7 * self._price_sensitivity + 0.3 * new_sensitivity
        self._price_sensitivity = max(1/5_000_000, min(1/100_000, self._price_sensitivity))


# ─── Price Ceiling Cache ──────────────────────────────────────────────────────
class PriceCeilingCache:
    def __init__(self, path: Path = CEILING_CACHE_FILE):
        self.path   = path
        self._cache: Dict[str, Dict] = {}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception:
                self._cache = {}
        self._loaded = True

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    def get(self, variant_id: str) -> Optional[int]:
        self._load()
        entry = self._cache.get(str(variant_id))
        if not entry:
            return None
        age = time.time() - entry.get("probed_at", 0)
        if age > CEILING_CACHE_TTL_SEC:
            return None
        return entry.get("ceiling")

    def set(
        self,
        variant_id:      str,
        ceiling:         int,
        reference_price: int,
        last_rejected:   Optional[int] = None,
    ):
        self._load()
        existing = self._cache.get(str(variant_id), {})
        self._cache[str(variant_id)] = {
            "ceiling":         ceiling,
            "reference_price": reference_price,
            "probed_at":       time.time(),
            "probe_count":     existing.get("probe_count", 0) + 1,
            "last_rejected":   last_rejected or ceiling + DEFAULT_STEP,
        }
        self._save()

    def invalidate(self, variant_id: str):
        self._load()
        self._cache.pop(str(variant_id), None)
        self._save()

    def get_all(self) -> Dict:
        self._load()
        return dict(self._cache)

_ceiling_cache = PriceCeilingCache()


# ─── موتور سناریو ─────────────────────────────────────────────────────────────
class ScenarioEngine:
    def __init__(self, predictor: BuyBoxScorePredictor, memory: AdaptiveMemory):
        self.predictor = predictor
        self.memory    = memory
        self.ceiling   = _ceiling_cache
        self.price_probe_fn: Optional[Callable[[str, int], bool]] = None

    def _effective_ceiling(
        self,
        variant_id:      str,
        reference_price: int,
        current_price:   int,
        max_price:       int,
    ) -> int:
        cached = self.ceiling.get(variant_id)
        if cached:
            return min(max_price, cached)

        if reference_price > 0:
            conservative = int(reference_price * 1.03 // DEFAULT_STEP * DEFAULT_STEP)
        else:
            conservative = current_price

        return min(max_price, conservative)

    def decide(self, d: StrategyInput) -> ScenarioResult:
        step = max(DEFAULT_STEP, int(d.step or DEFAULT_STEP))

        winner_info      = d.winner_info or {}
        comp_seller_id   = int(winner_info.get("seller_id") or 0)
        comp_seller_rate = float(winner_info.get("seller_rate") or 82.0)
        comp_lead_time   = int(winner_info.get("lead_time") or 2)

        effective_ceil = self._effective_ceiling(
            variant_id      = str(d.variant_id) if hasattr(d, "variant_id") else "0",
            reference_price = d.reference_price if hasattr(d, "reference_price") else 0,
            current_price   = d.current_price,
            max_price       = d.max_price,
        )

        def _score(price: int) -> float:
            return self.predictor.predict_score(
                my_price         = price,
                comp_price       = d.competitor_price if d.competitor_price > 0 else price + 1,
                my_seller_rate   = d.my_seller_rate,
                comp_seller_rate = comp_seller_rate,
                my_lead_time     = d.my_lead_time,
                comp_lead_time   = comp_lead_time,
            )

        def _snap(price: int, step_: int) -> int:
            p = int(round(price / step_) * step_)
            return max(d.min_price, min(effective_ceil, p))

        # ─── سناریو ۱: تنها در بازار ────────────────────────────────────────
        if d.alone_in_market or d.competitor_price <= 0:
            if d.current_price < effective_ceil:
                target = _snap(d.current_price + step, step)
                target = min(target, effective_ceil)
                return ScenarioResult(
                    target_price    = target,
                    predicted_score = 99.0,
                    scenario        = "alone_up",
                    reason          = f"تنها فروشنده — بالا میریم {d.current_price:,} → {target:,} (سقف: {effective_ceil:,})",
                    confidence      = 0.9,
                )
            return ScenarioResult(
                target_price    = d.current_price,
                predicted_score = 99.0,
                scenario        = "alone_hold",
                reason          = f"تنها فروشنده — روی سقف مجاز {effective_ceil:,} هستیم",
                confidence      = 1.0,
            )

        current_score = d.buy_box_score or _score(d.current_price)

        # ─── سناریو ۲: عقب‌نشینی سریع رقیب (پرش بلند) ────────────────────────
        # اگر رقیب قیمت را بیش از حد (۱.۵ برابر گام) بالا برده است، سریع خودمان را به او می‌رسانیم
        if d.is_buy_box_winner and d.competitor_price > d.current_price + step * 1.5:
            target = _snap(d.competitor_price - step, step)
            target = min(target, effective_ceil)
            
            if target > d.current_price:
                new_score = _score(target)
                if new_score >= 50.0:
                    return ScenarioResult(
                        target_price    = target,
                        predicted_score = new_score,
                        scenario        = "retreat_up",
                        reason          = f"پرش سریع: رقیب ({d.competitor_price:,}) دور است — ما: {d.current_price:,} → {target:,}",
                        confidence      = 0.85,
                    )

        # ─── سناریو ۳: طمع هوشمند و دائمی (افزایش قیمت با گام‌های کاهشی ۲۰->۱۰->۵) ────
        if d.is_buy_box_winner and current_score >= GREED_THRESHOLD:
            proposed_step = step
            min_allowed_step = 5000
            
            if comp_seller_id > 0:
                state = self.memory.get_state(comp_seller_id)
                observations = state.get("observations", [])
                
                # استخراج تمام گپ‌هایی که در گذشته منجر به باخت شده‌اند
                failed_gaps = [o["gap"] for o in observations if not o["won"]]
                # اگر هیچ باختی ثبت نشده، یک عدد بسیار منفی می‌گذاریم تا هر گامی مجاز باشد
                max_failed_gap = max(failed_gaps) if failed_gaps else -99999999
                
                current_gap = d.competitor_price - d.current_price
                
                # بررسی دودویی: کاهش گام تا جایی که وارد محدوده باخت قطعی نشویم
                while proposed_step >= min_allowed_step:
                    proposed_gap = current_gap - proposed_step
                    # اگر با این افزایش قیمت، گپ جدید ما هنوز از بزرگترین گپی که باختیم بزرگتر است (یعنی امن است)
                    if proposed_gap > max_failed_gap:
                        break
                    # در غیر این صورت، گام را نصف کن (مثلا از ۲۰ به ۱۰ هزار)
                    proposed_step //= 2
            
            if proposed_step < min_allowed_step:
                return ScenarioResult(
                    target_price    = d.current_price,
                    predicted_score = current_score,
                    scenario        = "greed_blocked",
                    reason          = f"طمع متوقف: مرز خطر (گام‌های کمتر از {max_failed_gap:,} قبلاً باخت داده‌اند)",
                    confidence      = 0.90,
                )
            
            # اعمال افزایش قیمت با گام کشف شده
            candidate = d.current_price + proposed_step
            # رند کردن بر اساس گام مجاز (تا با مضرب‌های ۵۰۰۰ یا ۱۰۰۰۰ هم سازگار باشد)
            candidate = int(round(candidate / min_allowed_step) * min_allowed_step)
            candidate = max(d.min_price, min(effective_ceil, candidate))

            if candidate <= d.current_price:
                 return ScenarioResult(
                    target_price    = d.current_price,
                    predicted_score = current_score,
                    scenario        = "greed_blocked",
                    reason          = f"طمع متوقف: محدودیت کف و سقف اجازه افزایش نمی‌دهد",
                    confidence      = 0.9,
                )

            if candidate > effective_ceil:
                return ScenarioResult(
                    target_price    = d.current_price,
                    predicted_score = current_score,
                    scenario        = "greed_ceiling",
                    reason          = f"طمع متوقف: به سقف سایت {effective_ceil:,} رسیدیم",
                    confidence      = 0.95,
                )

            new_score = _score(candidate)
            if new_score >= 50.0:
                return ScenarioResult(
                    target_price    = candidate,
                    predicted_score = new_score,
                    scenario        = "greed",
                    reason          = f"طمع هوشمند: +{proposed_step:,} ریال | پیش‌بینی امتیاز {new_score:.1f}",
                    confidence      = 0.80,
                )
            
            return ScenarioResult(
                target_price    = d.current_price,
                predicted_score = current_score,
                scenario        = "greed_blocked",
                reason          = f"طمع متوقف: افت شدید امتیاز ({new_score:.1f} < 50)",
                confidence      = 0.8,
            )

        # ─── سناریو ۴: نگه‌داری (در صورت بلاک شدن طمع به هر دلیلی) ──────────────
        if d.is_buy_box_winner:
            return ScenarioResult(
                target_price    = d.current_price,
                predicted_score = current_score,
                scenario        = "hold",
                reason          = f"در منطقه امن هستیم، روی قیمت فعلی نگه می‌داریم",
                confidence      = 0.85,
            )

        # ─── سناریو ۵: باخته‌ایم و باید جایگاه را پس بگیریم ──────────────────────
        optimal_gap, gap_confidence = self.memory.get_optimal_gap(comp_seller_id, step)

        target_win_price = self.predictor.find_price_for_score(
            target_score     = WIN_THRESHOLD + 5,
            comp_price       = d.competitor_price,
            my_seller_rate   = d.my_seller_rate,
            comp_seller_rate = comp_seller_rate,
            my_lead_time     = d.my_lead_time,
            comp_lead_time   = comp_lead_time,
            min_price        = d.min_price,
            max_price        = d.max_price,
        )
        target_gap_price = d.competitor_price - optimal_gap

        if gap_confidence > 0.6:
            final_target = target_gap_price
            confidence   = gap_confidence
            reason       = f"حافظه: بازیابی بهترین گپ={optimal_gap:,} | conf={gap_confidence:.0%}"
        else:
            final_target = min(target_win_price, target_gap_price)
            confidence   = 0.5 + gap_confidence * 0.3
            reason       = f"مدل: هدف امتیاز {WIN_THRESHOLD+5:.0f} | gap={optimal_gap:,}"

        final_target = _snap(final_target, step)

        if final_target == d.current_price:
            return ScenarioResult(
                target_price    = d.current_price,
                predicted_score = current_score,
                scenario        = "no_change",
                reason          = "قیمت هدف با قیمت فعلی برابره",
                confidence      = confidence,
            )

        predicted = _score(final_target)
        return ScenarioResult(
            target_price    = final_target,
            predicted_score = predicted,
            scenario        = "win",
            reason          = reason,
            confidence      = confidence,
        )


# ─── Singleton instances ──────────────────────────────────────────────────────
_memory    = AdaptiveMemory()
_predictor = BuyBoxScorePredictor(_memory)
_engine    = ScenarioEngine(_predictor, _memory)


# ─── Public API ─────────────────────────────────────────────────────────────
class AdaptiveSniperStrategy:
    name  = "adaptive_sniper"
    label = "Adaptive Sniper AI (Aggressive)"
    description = "طمع دائمی و کاهشی تا مرز ۵۰۰۰ ریال برای حداکثر حاشیه سود"

    def __init__(self):
        self.memory    = _memory
        self.predictor = _predictor
        self.engine    = _engine

    @staticmethod
    def _clamp(target: int, min_price: int, max_price: int) -> int:
        return max(min_price, min(max_price, target))

    def decide(self, d: StrategyInput) -> Optional[int]:
        result = self.engine.decide(d)

        if result.scenario == "no_change":
            return None
        if result.scenario == "hold":
            return None

        # برای اینکه اجازه بدیم قیمت ۵۰۰۰ تایی هم بالا بره،
        # استپ پیش‌فرض رو دیگه فورس نمی‌کنیم و به نتیجه‌ی موتور احترام می‌ذاریم.
        target = self._clamp(result.target_price, d.min_price, d.max_price)

        if target == d.current_price:
            return None

        return target

    def decide_with_details(self, d: StrategyInput) -> ScenarioResult:
        return self.engine.decide(d)


ADAPTIVE_STRATEGY = AdaptiveSniperStrategy()

STRATEGIES: Dict[str, AdaptiveSniperStrategy] = {
    "adaptive_sniper": ADAPTIVE_STRATEGY,
    "smart":           ADAPTIVE_STRATEGY,
    "aggressive":      ADAPTIVE_STRATEGY,
    "conservative":    ADAPTIVE_STRATEGY,
    "step_up":         ADAPTIVE_STRATEGY,
}

STRATEGY_INFO = [
    {
        "key":   "adaptive_sniper",
        "label": AdaptiveSniperStrategy.label,
        "desc":  AdaptiveSniperStrategy.description,
    }
]


def get_strategy(name: str) -> AdaptiveSniperStrategy:
    return STRATEGIES.get(name, ADAPTIVE_STRATEGY)