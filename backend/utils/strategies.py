"""
backend/utils/strategies.py

BuyBox Score Engine — پیش‌بینی امتیاز بای‌باکس + سناریوهای هوشمند
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
LEARNING_MEMORY_FILE = BASE_DIR / "learning_memory.json"

# ─── ثابت‌های امتیازدهی (از تحلیل CSV لاگ استخراج شده) ──────────────────────
# رنک بای‌باکس = امتیاز ۰ تا ۱۰۰ (هرچه بالاتر = برنده‌تر)
# رنک تنوع = رنک کلی تنوع در صفحه محصول

# وزن‌های مدل امتیازدهی (از تحلیل داده‌های واقعی)
# BuyBox_Score ≈ w_price * price_score + w_seller * seller_score + w_lead * lead_score
W_PRICE  = 0.72   # قیمت بیشترین وزن رو داره
W_SELLER = 0.20   # امتیاز فروشنده
W_LEAD   = 0.08   # زمان ارسال

# آستانه‌های سناریو
GREED_THRESHOLD      = 95.0   # اگه امتیاز > 95، حریصانه قیمت رو بالا ببر
SAFE_ZONE_MIN        = 85.0   # اگه امتیاز > 85، در منطقه امن هستی
WIN_THRESHOLD        = 80.0   # معمولاً بالای ۸۰ بای‌باکس گرفته میشه
RETREAT_THRESHOLD    = 60.0   # زیر ۶۰ = باید عقب بکشی
GREED_STEP           = 20_000  # گام بالا بردن قیمت در حالت طمع
DEFAULT_STEP         = 20_000  # گام پیش‌فرض (تغییر از 1000 به 20000)


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
    buy_box_score:     Optional[float] = None   # امتیاز واقعی از API (اگه موجود)


@dataclass
class ScenarioResult:
    """نتیجه‌ی یک چرخه تصمیم‌گیری"""
    target_price:   int
    predicted_score: float
    scenario:       str   # greed / win / hold / retreat / alone
    reason:         str
    confidence:     float  # 0.0 تا 1.0


# ─── حافظه تطبیقی ─────────────────────────────────────────────────────────────
class AdaptiveMemory:
    """
    حافظه per-seller با تاریخچه کامل برای بهبود تدریجی پیش‌بینی.
    ساختار: {seller_id: {observations: [...], best_gap: int, win_rate: float}}
    """

    MAX_OBS = 30  # حداکثر تعداد مشاهده per seller

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
        """ثبت نتیجه + محاسبه best_gap و win_rate بر اساس تاریخچه"""
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
            "gap":       int(max(0, gap)),
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

        # بهترین gap = کمترین gap‌ای که برنده شده (حداکثر سود)
        best_gap = min((o["gap"] for o in wins), default=gap) if wins else gap

        entry.update({
            "observations": observations,
            "best_gap":     int(best_gap),
            "win_rate":     round(win_rate, 3),
            "last_gap":     int(max(0, gap)),
            "last_result":  "win" if won else "loss",
        })
        self._cache[sid] = entry
        self._save()

    def get_optimal_gap(self, competitor_seller_id: int, default_step: int) -> Tuple[int, float]:
        """
        برگرداندن بهترین gap + اطمینان (confidence).
        confidence بالا = داده‌های کافی داریم
        """
        self._load()
        state = self._cache.get(str(competitor_seller_id), {})
        observations = state.get("observations", [])

        if len(observations) < 3:
            return default_step, 0.2  # کم‌تجربه

        wins = [o for o in observations if o["won"]]
        if not wins:
            # هیچ برنده‌ای نداریم → gap رو کم کن
            last_gap = state.get("last_gap", default_step)
            return max(default_step, last_gap - default_step // 2), 0.3

        best_gap  = min(o["gap"] for o in wins)
        win_rate  = len(wins) / len(observations)
        confidence = min(0.95, win_rate * (len(observations) / 15))

        # اگه در ۵ مشاهده اخیر همیشه بردیم، کمی explore کن (gap رو کم کن)
        recent = observations[-5:]
        recent_win_rate = sum(1 for o in recent if o["won"]) / len(recent)
        if recent_win_rate == 1.0 and best_gap > default_step:
            explore_gap = max(default_step // 2, best_gap - default_step)
            return explore_gap, confidence * 0.8  # کمی confidence کمتر چون explore می‌کنیم

        return best_gap, confidence


# ─── BuyBox Score Predictor ───────────────────────────────────────────────────
class BuyBoxScorePredictor:
    """
    پیش‌بینی امتیاز بای‌باکس بر اساس فرمول استخراج شده از داده‌های واقعی.

    از لاگ CSV داریم:
    - Behin Tajhizat: قیمت ۲۱,۷۵۰,۰۰۰ → BuyBox_Rank=88.85, seller_rate=82
    - Daryaye Aram: قیمت ۲۱,۵۰۰,۰۰۰ → BuyBox_Rank=90.01 (برنده)
    - Daryaye Aram: قیمت ۲۱,۰۰۰,۰۰۰ → BuyBox_Rank=91.90 (برنده)

    الگو: هر ۵۰۰,۰۰۰ کاهش قیمت ≈ +۱ امتیاز بای‌باکس
    """

    def __init__(self, memory: AdaptiveMemory):
        self.memory = memory
        # ضرایب مدل — با هر مشاهده جدید کالیبره می‌شن
        self._price_sensitivity = 1.0 / 500_000   # هر ۵۰۰k ریال = ~۱ امتیاز

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
        """
        پیش‌بینی امتیاز بای‌باکس ما در برابر یه رقیب مشخص.
        """
        # مولفه قیمت
        price_delta = (comp_price - my_price) * self._price_sensitivity
        price_component = price_delta * 100 * W_PRICE

        # مولفه فروشنده
        seller_delta = (my_seller_rate - comp_seller_rate) / 100
        seller_component = seller_delta * 100 * W_SELLER

        # مولفه زمان ارسال
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
        """
        محاسبه‌ی قیمتی که منجر به امتیاز هدف می‌شه.
        معکوس فرمول predict_score.
        """
        # seller + lead components (ثابت)
        seller_delta   = (my_seller_rate - comp_seller_rate) / 100
        seller_comp    = seller_delta * 100 * W_SELLER
        lead_delta     = (comp_lead_time - my_lead_time)
        lead_comp      = lead_delta * 5 * W_LEAD

        # حل برای price_component:
        # target = base + price_comp + seller_comp + lead_comp
        # price_comp = (target - base - seller_comp - lead_comp)
        needed_price_comp = target_score - base_score - seller_comp - lead_comp
        # price_comp = (comp_price - my_price) * sensitivity * 100 * W_PRICE
        # → my_price = comp_price - needed_price_comp / (sensitivity * 100 * W_PRICE)
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
        """
        کالیبراسیون مدل بر اساس مشاهده واقعی.
        تنظیم _price_sensitivity.
        """
        price_diff = comp_price - my_price
        if abs(price_diff) < 1000:
            return  # تفاوت کمه، قابل کالیبره نیست

        seller_delta = (my_seller_rate - comp_seller_rate) / 100
        seller_comp  = seller_delta * 100 * W_SELLER

        # score = base + price_delta * sensitivity * 100 * W_PRICE + seller_comp
        # → sensitivity = (score - base - seller_comp) / (price_diff * 100 * W_PRICE)
        base = 88.0
        numerator = observed_score - base - seller_comp
        denominator = price_diff * 100 * W_PRICE

        if abs(denominator) < 1e-9:
            return

        new_sensitivity = numerator / denominator
        # moving average برای جلوگیری از نوسان
        self._price_sensitivity = 0.7 * self._price_sensitivity + 0.3 * new_sensitivity
        self._price_sensitivity = max(1/5_000_000, min(1/100_000, self._price_sensitivity))


# ─── موتور سناریو ─────────────────────────────────────────────────────────────
class ScenarioEngine:
    """
    تصمیم‌گیری بر اساس سناریوهای تعریف‌شده + پیش‌بینی امتیاز.
    """

    def __init__(self, predictor: BuyBoxScorePredictor, memory: AdaptiveMemory):
        self.predictor = predictor
        self.memory    = memory

    def decide(self, d: StrategyInput) -> ScenarioResult:

        step = max(DEFAULT_STEP, int(d.step or DEFAULT_STEP))

        winner_info       = d.winner_info or {}
        comp_seller_id    = int(winner_info.get("seller_id") or 0)
        comp_seller_rate  = float(winner_info.get("seller_rate") or 82.0)
        comp_lead_time    = int(winner_info.get("lead_time") or 2)
        item_votes        = int(winner_info.get("item_votes") or 0)

        # ─── تنها در بازار ───────────────────────────────────────────────────
        if d.alone_in_market or d.competitor_price <= 0:
            return ScenarioResult(
                target_price    = d.max_price,
                predicted_score = 99.0,
                scenario        = "alone",
                reason          = "تنها فروشنده — حداکثر قیمت",
                confidence      = 1.0,
            )

        # امتیاز فعلی ما
        current_score = d.buy_box_score or self.predictor.predict_score(
            my_price         = d.current_price,
            comp_price       = d.competitor_price,
            my_seller_rate   = d.my_seller_rate,
            comp_seller_rate = comp_seller_rate,
            my_lead_time     = d.my_lead_time,
            comp_lead_time   = comp_lead_time,
        )

        # ─── سناریو طمع (Greed) ──────────────────────────────────────────────
        # داریم بای‌باکس رو و امتیاز خیلی بالاست → قیمت رو بالا ببر
        if d.is_buy_box_winner and current_score >= GREED_THRESHOLD:
            new_price = min(d.max_price, d.current_price + step)
            new_score = self.predictor.predict_score(
                my_price         = new_price,
                comp_price       = d.competitor_price,
                my_seller_rate   = d.my_seller_rate,
                comp_seller_rate = comp_seller_rate,
                my_lead_time     = d.my_lead_time,
                comp_lead_time   = comp_lead_time,
            )
            if new_score >= WIN_THRESHOLD:
                return ScenarioResult(
                    target_price    = new_price,
                    predicted_score = new_score,
                    scenario        = "greed",
                    reason          = f"امتیاز {current_score:.1f} > {GREED_THRESHOLD} → طمع +{step:,}",
                    confidence      = 0.7,
                )

        # ─── سناریو نگه‌داری (Hold) ─────────────────────────────────────────
        # داریم بای‌باکس رو و امتیاز در منطقه امن است
        if d.is_buy_box_winner and SAFE_ZONE_MIN <= current_score < GREED_THRESHOLD:
            return ScenarioResult(
                target_price    = d.current_price,
                predicted_score = current_score,
                scenario        = "hold",
                reason          = f"امتیاز {current_score:.1f} در منطقه امن — نگه می‌داریم",
                confidence      = 0.8,
            )

        # ─── سناریو عقب‌نشینی (Retreat) ────────────────────────────────────
        # رقیب کشید عقب یا قیمت رقیب خیلی بالاتر از ما → ما هم قیمت رو بالا ببریم
        if d.is_buy_box_winner and d.competitor_price > d.current_price * 1.05:
            new_price = min(d.max_price, d.competitor_price - step)
            new_score = self.predictor.predict_score(
                my_price         = new_price,
                comp_price       = d.competitor_price,
                my_seller_rate   = d.my_seller_rate,
                comp_seller_rate = comp_seller_rate,
                my_lead_time     = d.my_lead_time,
                comp_lead_time   = comp_lead_time,
            )
            if new_score >= WIN_THRESHOLD:
                return ScenarioResult(
                    target_price    = new_price,
                    predicted_score = new_score,
                    scenario        = "retreat_up",
                    reason          = f"رقیب کشید عقب به {d.competitor_price:,} — ما هم بالا میریم",
                    confidence      = 0.75,
                )

        # ─── سناریو برنده شدن (Win) ─────────────────────────────────────────
        # بای‌باکس نداریم → محاسبه قیمت برای برنده شدن
        optimal_gap, gap_confidence = self.memory.get_optimal_gap(comp_seller_id, step)

        # قیمت هدف برای برنده شدن
        target_win_price = self.predictor.find_price_for_score(
            target_score     = WIN_THRESHOLD + 5,  # کمی بالاتر از آستانه
            comp_price       = d.competitor_price,
            my_seller_rate   = d.my_seller_rate,
            comp_seller_rate = comp_seller_rate,
            my_lead_time     = d.my_lead_time,
            comp_lead_time   = comp_lead_time,
            min_price        = d.min_price,
            max_price        = d.max_price,
        )

        # قیمت بر اساس gap حافظه
        target_gap_price = d.competitor_price - optimal_gap

        # اگه confidence حافظه بالاست از gap استفاده کن، وگرنه از مدل
        if gap_confidence > 0.6:
            final_target = target_gap_price
            confidence   = gap_confidence
            reason       = f"حافظه: gap={optimal_gap:,} | conf={gap_confidence:.0%}"
        else:
            final_target = min(target_win_price, target_gap_price)
            confidence   = 0.5 + gap_confidence * 0.3
            reason       = f"مدل: هدف امتیاز {WIN_THRESHOLD+5} | gap={optimal_gap:,}"

        final_target = max(d.min_price, min(d.max_price, final_target))
        final_target = int(round(final_target / DEFAULT_STEP) * DEFAULT_STEP)

        # اگه هدف با قیمت فعلی یکیه → رد کن
        if final_target == d.current_price:
            return ScenarioResult(
                target_price    = d.current_price,
                predicted_score = current_score,
                scenario        = "no_change",
                reason          = "قیمت هدف با قیمت فعلی برابره",
                confidence      = confidence,
            )

        predicted = self.predictor.predict_score(
            my_price         = final_target,
            comp_price       = d.competitor_price,
            my_seller_rate   = d.my_seller_rate,
            comp_seller_rate = comp_seller_rate,
            my_lead_time     = d.my_lead_time,
            comp_lead_time   = comp_lead_time,
        )

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


# ─── Public API (سازگار با کد قبلی) ──────────────────────────────────────────
class AdaptiveSniperStrategy:
    """Wrapper برای سازگاری با repricer_engine.py"""

    name  = "adaptive_sniper"
    label = "Adaptive Sniper AI"
    description = "موتور امتیازدهی BuyBox + سناریوهای هوشمند طمع/عقب‌نشینی/برنده‌شدن"

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

        target = self._clamp(result.target_price, d.min_price, d.max_price)
        target = int(round(target / DEFAULT_STEP) * DEFAULT_STEP)

        if target == d.current_price:
            return None

        return target

    def decide_with_details(self, d: StrategyInput) -> ScenarioResult:
        """نسخه کامل با جزئیات برای cache monitor"""
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