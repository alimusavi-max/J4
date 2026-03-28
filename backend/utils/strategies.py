"""
backend/utils/strategies.py

استراتژی‌های قیمت‌گذاری — ساده، واضح، per-variant

هر استراتژی یک تابع decide() دارد:
  ورودی: StrategyInput
  خروجی: قیمت پیشنهادی (int) یا None (= هیچ کاری نکن)
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class StrategyInput:
    competitor_price: int    # ارزان‌ترین رقیب (از API عمومی دیجی‌کالا)
    current_price: int       # قیمت فعلی من
    min_price: int           # کف مجاز (تنظیم کاربر)
    max_price: int           # سقف مجاز (تنظیم کاربر)
    step: int                # گام قیمت این تنوع
    is_buy_box_winner: bool  # آیا الان buybox دارم؟
    alone_in_market: bool    # آیا رقیبی نیست؟


class AggressiveStrategy:
    """
    تهاجمی:
    - رقیب دارم  → step زیر رقیب بزن
    - رقیب نیست  → تا سقف برو
    - زیر کف هرگز
    """
    name = "aggressive"
    label = "تهاجمی"
    description = "همیشه یک گام زیر ارزان‌ترین رقیب. اگر رقیبی نباشد تا سقف می‌رود."

    def decide(self, d: StrategyInput) -> Optional[int]:
        if d.alone_in_market or d.competitor_price <= 0:
            return d.max_price

        target = d.competitor_price - d.step
        if target < d.min_price:
            return None  # رقیب خیلی ارزانه، صبر کن
        return min(target, d.max_price)


class ConservativeStrategy:
    """
    محافظه‌کار:
    - فقط اگه رقیب بیشتر از 3 گام ارزون‌تره وارد رقابت بشم
    - buybox دارم و رقیب نزدیکه → نگه‌دار
    - تنها در بازار → یک گام بالا (نه یکدفعه تا سقف)
    """
    name = "conservative"
    label = "محافظه‌کار"
    description = "فقط وقتی رقیب بیش از ۳ گام پایین‌تر است وارد رقابت می‌شود."

    def decide(self, d: StrategyInput) -> Optional[int]:
        if d.alone_in_market or d.competitor_price <= 0:
            target = min(d.current_price + d.step, d.max_price)
            return target if target > d.current_price else None

        gap = d.current_price - d.competitor_price
        if gap > d.step * 3:
            target = d.competitor_price - d.step
            if target < d.min_price:
                return None
            return min(target, d.max_price)

        if d.is_buy_box_winner:
            return None  # buybox دارم و رقیب نزدیکه → نگه‌دار

        # buybox ندارم ولی فاصله کمه → یک گام پایین
        target = d.current_price - d.step
        if target < d.min_price:
            return None
        return target


class StepUpStrategy:
    """
    سود-محور:
    - buybox دارم  → هر چرخه یک گام بالا برو (تا سقف)
    - buybox ندارم → یک گام زیر رقیب
    """
    name = "step_up"
    label = "سود-محور"
    description = "وقتی بای‌باکس دارد آرام قیمت را بالا می‌برد. وقتی ندارد زیر رقیب می‌رود."

    def decide(self, d: StrategyInput) -> Optional[int]:
        if d.alone_in_market or d.competitor_price <= 0:
            target = min(d.current_price + d.step, d.max_price)
            return target if target > d.current_price else None

        if d.is_buy_box_winner:
            target = min(d.current_price + d.step, d.max_price)
            if target >= d.competitor_price:
                return None  # خطر از دست دادن buybox
            return target if target > d.current_price else None

        target = d.competitor_price - d.step
        if target < d.min_price:
            return None
        return min(target, d.max_price)


# ─── رجیستری ──────────────────────────────────────────────────────────────────
STRATEGIES: dict = {
    "aggressive":   AggressiveStrategy(),
    "conservative": ConservativeStrategy(),
    "step_up":      StepUpStrategy(),
}

STRATEGY_INFO = [
    {"key": "aggressive",   "label": "تهاجمی",       "desc": AggressiveStrategy.description},
    {"key": "conservative", "label": "محافظه‌کار",    "desc": ConservativeStrategy.description},
    {"key": "step_up",      "label": "سود-محور",      "desc": StepUpStrategy.description},
]


def get_strategy(name: str):
    return STRATEGIES.get(name, STRATEGIES["aggressive"])