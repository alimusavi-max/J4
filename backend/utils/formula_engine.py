"""
موتور فرمول - ارزیابی امن فرمول‌های قیمت‌گذاری
"""
import math
import re
from typing import Dict, Any, Optional

# توابع مجاز در فرمول
ALLOWED_FUNCTIONS = {
    'min': min,
    'max': max,
    'abs': abs,
    'round': round,
    'floor': math.floor,
    'ceil': math.ceil,
    'int': int,
    'float': float,
    'sqrt': math.sqrt,
}

# متغیرهای قابل استفاده در فرمول‌ها
FORMULA_VARIABLES_HELP = {
    'competitor_price': 'قیمت ارزان‌ترین رقیب',
    'reference_price':  'قیمت مرجع (لیست)',
    'current_price':    'قیمت فعلی من',
    'step_price':       'گام قیمت',
    'min_price':        'کف قیمت تنظیم‌شده',
    'cost':             'قیمت تمام‌شده (در صورت تنظیم)',
    'buy_box_price':    'قیمت فعلی بای‌باکس',
}

# فرمول‌های پیش‌فرض پیشنهادی
PRESET_FORMULAS = {
    'buybox': [
        {"label": "یک گام زیر رقیب (پیش‌فرض)",   "formula": "competitor_price - step_price"},
        {"label": "یک درصد زیر رقیب",              "formula": "competitor_price * 0.99"},
        {"label": "دو گام زیر رقیب",               "formula": "competitor_price - step_price * 2"},
        {"label": "زیر رقیب ولی بالای کف",         "formula": "max(competitor_price - step_price, min_price)"},
    ],
    'min_price': [
        {"label": "۷۵٪ قیمت مرجع",  "formula": "reference_price * 0.75"},
        {"label": "۸۰٪ قیمت مرجع",  "formula": "reference_price * 0.80"},
        {"label": "۷۰٪ قیمت مرجع",  "formula": "reference_price * 0.70"},
        {"label": "هزینه + ۲۰٪ سود", "formula": "cost * 1.20"},
    ],
}

BLOCKED_KEYWORDS = ['import', 'exec', 'eval', 'open', 'os', 'sys', '__', 'getattr', 'setattr']


def _safe_eval(formula: str, variables: Dict[str, Any]) -> float:
    """ارزیابی امن فرمول با محدودیت دسترسی"""
    clean = formula.strip()

    # بررسی کاراکترهای مجاز
    pattern = re.compile(r'^[\d\s\+\-\*\/\(\)\.\,\_a-zA-Z]+$')
    if not pattern.match(clean):
        raise ValueError(f"فرمول حاوی کاراکتر غیرمجاز است")

    # بررسی کلمات ممنوع
    for word in BLOCKED_KEYWORDS:
        if word in clean.lower():
            raise ValueError(f"کلمه غیرمجاز در فرمول: '{word}'")

    namespace = {**ALLOWED_FUNCTIONS, **variables}
    try:
        result = eval(clean, {"__builtins__": {}}, namespace)
        return float(result)
    except ZeroDivisionError:
        raise ValueError("تقسیم بر صفر در فرمول")
    except NameError as e:
        bad_name = str(e).split("'")[1] if "'" in str(e) else str(e)
        raise ValueError(f"متغیر ناشناخته: '{bad_name}'. متغیرهای مجاز: {', '.join(FORMULA_VARIABLES_HELP.keys())}")
    except SyntaxError:
        raise ValueError("خطای نحوی در فرمول - لطفاً فرمول را بررسی کنید")
    except Exception as e:
        raise ValueError(f"خطا در محاسبه: {e}")


def calculate_price(formula: str, variables: Dict[str, Any], round_to: int = 1000) -> int:
    """
    محاسبه قیمت از فرمول و گرد کردن به نزدیک‌ترین مضرب
    
    Args:
        formula: فرمول ریاضی مثل 'competitor_price - step_price'
        variables: مقادیر متغیرها
        round_to: گرد کردن به این مضرب (پیش‌فرض: ۱۰۰۰ تومان)
    
    Returns:
        قیمت محاسبه‌شده به صورت عدد صحیح
    """
    result = _safe_eval(formula, variables)
    if result <= 0:
        raise ValueError(f"قیمت حاصل ({result:,.0f}) باید مثبت باشد")
    rounded = int(round(result / round_to) * round_to)
    return max(rounded, round_to)


def calculate_buybox_price(
    formula: str,
    competitor_price: int,
    reference_price: int,
    current_price: int,
    step_price: int = 1000,
    min_price: int = 0,
    buy_box_price: int = 0,
) -> int:
    """محاسبه قیمت هدف بای‌باکس از فرمول"""
    variables = {
        'competitor_price': competitor_price,
        'reference_price':  reference_price or current_price,
        'current_price':    current_price,
        'step_price':       step_price,
        'min_price':        min_price,
        'buy_box_price':    buy_box_price or current_price,
        'cost':             0,
    }
    return calculate_price(formula, variables)


def calculate_min_price(
    formula: str,
    reference_price: int,
    current_price: int,
    step_price: int = 1000,
    cost: int = 0,
) -> int:
    """محاسبه کف قیمت از فرمول"""
    variables = {
        'reference_price': reference_price or current_price,
        'current_price':   current_price,
        'step_price':      step_price,
        'cost':            cost,
        'min_price':       0,
        'competitor_price': 0,
        'buy_box_price':   0,
    }
    return calculate_price(formula, variables)


def test_formula(formula: str, sample_values: Dict[str, float]) -> dict:
    """تست فرمول با مقادیر نمونه - برای نمایش پیش‌نمایش در UI"""
    if not formula or not formula.strip():
        return {"success": False, "error": "فرمول خالی است"}
    try:
        result = calculate_price(formula, sample_values)
        return {"success": True, "result": result, "formula": formula}
    except ValueError as e:
        return {"success": False, "error": str(e), "formula": formula}
