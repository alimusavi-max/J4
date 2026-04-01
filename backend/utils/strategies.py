"""
backend/utils/strategies.py

استراتژی قیمت‌گذاری — ساده‌سازی شده به یک استراتژی هوشمند تک‌منظوره
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class StrategyInput:
    competitor_price: int    # ارزان‌ترین رقیب
    current_price: int       # قیمت فعلی من
    min_price: int           # کف مجاز
    max_price: int           # سقف مجاز
    step: int                # گام قیمت (مثلا 10000)
    is_buy_box_winner: bool  # آیا الان buybox دارم؟
    alone_in_market: bool    # آیا رقیبی نیست؟
    winner_info: Dict[str, Any] = None # اطلاعات برنده برای تشخیص غول‌ها


class SmartStrategy:
    """
    استراتژی هوشمند (تنها استراتژی سیستم):
    ۱. برنده هستم:
       - رقیب نیست -> برو به سقف قیمت
       - رقیب هست -> قیمت را ببر دقیقاً یک گام زیر نفر دوم (بیشینه‌سازی سود)
    ۲. بازنده هستم:
       - رقیب غول است (بالای 10هزار رای) -> 1.2 درصد زیر قیمت او
       - رقیب معمولی است -> یک گام (step) زیر قیمت او
    """
    name = "smart"
    label = "هوشمند (Profit & Attack)"
    description = "به صورت خودکار رقبای قدرتمند را تشخیص داده و در زمان پیروزی، سود را ماکزیمم می‌کند."

    def decide(self, d: StrategyInput) -> Optional[int]:
        target = None
        
        # ─── حالت ۱: من برنده هستم (بیشینه‌سازی سود) ───
        if d.is_buy_box_winner:
            if d.alone_in_market or d.competitor_price <= 0:
                # تنها هستم، پرواز به سقف
                target = d.max_price
            else:
                # رقیب دارم، قیمت را می‌برم یک پله زیر ارزان‌ترین رقیب
                target = d.competitor_price - d.step
                if target > d.max_price:
                    target = d.max_price
                if target <= d.current_price:
                    return None # جایگاهم خوب است، تغییری نیاز نیست
                    
            return target

        # ─── حالت ۲: من بازنده هستم (حمله به بای‌باکس) ───
        if not d.winner_info:
             # اطلاعاتی از برنده نداریم، استاندارد حمله می‌کنیم
             target = d.current_price - d.step
        else:
            w_price = d.winner_info.get("price", 0)
            w_votes = d.winner_info.get("votes", 0)
            my_votes = 460 # TODO: می‌تواند بعداً از پروفایل شما خوانده شود
            
            # تشخیص رقیب غول‌پیکر
            if w_votes > 10000 and my_votes < 1000:
                drop_amount = int(w_price * 0.012) # 1.2 درصد کاهش
                target = w_price - drop_amount
                target = (target // 10000) * 10000 # رند کردن به ده هزار تومان
            else:
                # رقیب معمولی
                target = w_price - d.step
                
        # اعمال گارد ضرر
        if target < d.min_price:
            return None # نمی‌ارزد
            
        return min(target, d.max_price)

# ─── رجیستری ──────────────────────────────────────────────────────────────────
# حالا فقط یک استراتژی داریم
STRATEGIES: dict = {
    "smart": SmartStrategy(),
    # برای جلوگیری از کرش کردن فرانت‌اند اگر دیتابیس قدیمی نام استراتژی‌های قبلی را ذخیره کرده باشد:
    "aggressive": SmartStrategy(),
    "conservative": SmartStrategy(),
    "step_up": SmartStrategy(),
}

STRATEGY_INFO = [
    {"key": "smart", "label": "هوشمند (Profit & Attack)", "desc": SmartStrategy.description},
]

def get_strategy(name: str):
    return STRATEGIES.get(name, STRATEGIES["smart"])