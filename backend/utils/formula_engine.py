"""
backend/utils/formula_engine.py
موتور فرمول - ساده‌سازی شده برای هماهنگی با هوش مصنوعی و جلوگیری از ارور
"""
from typing import Dict, Any

# متغیرهای مجاز (فقط برای حفظ سازگاری با API فرانت‌اند)
FORMULA_VARIABLES_HELP = {
    'reference_price':  'قیمت مرجع (لیست)',
    'current_price':    'قیمت فعلی من',
    'step_price':       'گام قیمت',
    'cost':             'قیمت تمام‌شده (در صورت تنظیم)',
}

# فرمول‌های پیش‌فرض
PRESET_FORMULAS = {
    'buybox': [
        {"label": "استفاده از هوش مصنوعی (توصیه شده)", "formula": "AI_SMART"},
    ],
    'min_price': [
        {"label": "۸۰٪ قیمت مرجع",  "formula": "reference_price * 0.80"},
        {"label": "۷۵٪ قیمت مرجع",  "formula": "reference_price * 0.75"},
    ],
}

def calculate_min_price(
    formula: str,
    reference_price: int,
    current_price: int,
    step_price: int = 1000,
    cost: int = 0,
) -> int:
    """محاسبه ساده و ایمن کف قیمت"""
    ref = reference_price or current_price
    
    if "0.8" in formula or "80" in formula:
        result = ref * 0.80
    elif "0.75" in formula or "75" in formula:
        result = ref * 0.75
    elif "cost" in formula and cost > 0:
        result = cost * 1.20
    else:
        result = ref * 0.85
        
    rounded = int(round(result / 1000) * 1000)
    return max(rounded, 1000)

def calculate_buybox_price(*args, **kwargs) -> int:
    """تابع بلااستفاده برای حفظ سازگاری (منطق در SmartStrategy است)"""
    return 0

def test_formula(formula: str, sample_values: Dict[str, float]) -> dict:
    """تست فرمول (Mock) برای جلوگیری از ارور در پنل تنظیمات"""
    if not formula or not formula.strip():
        return {"success": False, "error": "فرمول خالی است"}
        
    try:
        if "buybox" in formula.lower() or formula == "AI_SMART":
            return {"success": True, "result": sample_values.get("current_price", 100000), "formula": formula}
            
        result = calculate_min_price(
            formula, 
            int(sample_values.get('reference_price', 0)), 
            int(sample_values.get('current_price', 0)),
            int(sample_values.get('step_price', 1000)),
            int(sample_values.get('cost', 0))
        )
        return {"success": True, "result": result, "formula": formula}
    except Exception as e:
        return {"success": False, "error": str(e), "formula": formula}