"""
backend/main.py
"""
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Union, Optional
import json, time, threading
from pathlib import Path
from datetime import datetime

from utils.repricer_engine import DigikalaRepricer
from utils.formula_engine import (
    test_formula, calculate_min_price,
    PRESET_FORMULAS, FORMULA_VARIABLES_HELP,
)
from utils.strategies import STRATEGY_INFO

app = FastAPI(title="Digikala Repricer API", version="4.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

BASE_DIR      = Path(__file__).resolve().parent
CONFIG_FILE   = BASE_DIR / "repricer_config.json"
SETTINGS_FILE = BASE_DIR / "repricer_settings.json"

DEFAULT_SETTINGS = {
    "lead_time":                2,
    "shipping_type":            "seller",
    "max_per_order":            4,
    "request_delay_min":        3.0,
    "request_delay_max":        6.0,
    "rate_limit_backoff_base":  15,
    "max_retries":              3,
    "default_strategy":         "aggressive",
    "default_step":             1000,
    "dry_run":                  False,
    "variant_cooldown_seconds": 300,
    "notify_webhook_url":       "",
    "rate_limit_pause_seconds": 180,
    "max_consecutive_failures": 10,
    "my_seller_id":             0,
}

bot_state = {
    "is_running":      False,
    "workspace_id":    1,
    "started_at":      None,
    "cycle_count":     0,
    "total_updates":   0,
    "buybox_wins":     0,
    "rate_limit_hits": 0,
}
logs: list = []
logs_lock = threading.Lock()


def save_log(msg: str):
    with logs_lock:
        logs.append({"msg": msg, "time": datetime.now().isoformat()})
        if len(logs) > 500:
            logs.pop(0)


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_SETTINGS, **json.load(f)}
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


# ─── Bot loop ─────────────────────────────────────────────────────────────────
def run_bot_loop(workspace_id: int, cycle_delay: int = 120):
    bot = DigikalaRepricer(workspace_id, log_callback=save_log)

    while bot_state["is_running"]:
        try:
            configs  = _load_config()
            settings = _load_settings()
            result   = bot.evaluate_and_act_all(
                configs,
                global_step=int(settings.get("default_step", 1000)),
                my_seller_id=int(settings.get("my_seller_id", 0)),
            )
        except Exception as e:
            save_log(f"❌ خطای پیش‌بینی‌نشده در چرخه: {e}")
            result = {"updated_count": 0, "buybox_count": 0, "rate_limit_hits": 0}

        bot_state["cycle_count"]    += 1
        bot_state["total_updates"]  += result.get("updated_count", 0)
        bot_state["buybox_wins"]     = result.get("buybox_count", 0)
        bot_state["rate_limit_hits"] += result.get("rate_limit_hits", 0)

        for _ in range(cycle_delay):
            if not bot_state["is_running"]:
                break
            time.sleep(1)


# ─── Pydantic models ──────────────────────────────────────────────────────────
class ConfigModel(BaseModel):
    configs: dict

class BotStartModel(BaseModel):
    workspace_id: int = 1
    cycle_delay:  int = 120

class TestPriceModel(BaseModel):
    workspace_id: int
    variant_id:   str
    test_price:   int

class DiscoverModel(BaseModel):
    workspace_id:    int
    variant_id:      Union[int, str]
    reference_price: int
    current_price:   int

class SettingsModel(BaseModel):
    lead_time:                int   = 2
    shipping_type:            str   = "seller"
    max_per_order:            int   = 4
    request_delay_min:        float = 3.0
    request_delay_max:        float = 6.0
    rate_limit_backoff_base:  int   = 15
    max_retries:              int   = 3
    default_strategy:         str   = "aggressive"
    default_step:             int   = 1000
    dry_run:                  bool  = False
    variant_cooldown_seconds: int   = 300
    notify_webhook_url:       str   = ""
    rate_limit_pause_seconds: int   = 180
    max_consecutive_failures: int   = 10
    my_seller_id:             int   = 0

class FormulaTestModel(BaseModel):
    formula:       str
    formula_type:  str  = "buybox"
    sample_values: dict = {}

class ApplyMinFormulaModel(BaseModel):
    workspace_id: int = 1
    formula:      str
    step_price:   int = 1000

class VariantConfigModel(BaseModel):
    """Config برای یک تنوع خاص"""
    variant_id: str
    min_price:  Optional[int] = None
    max_price:  Optional[int] = None
    enabled:    bool = True
    strategy:   str  = "aggressive"
    step:       Optional[int] = None
    product_id: Optional[int] = None   # برای API عمومی دیجی‌کالا

class CompetitorPriceModel(BaseModel):
    product_id:    int
    my_seller_id:  int = 0
    workspace_id:  int = 1


# ─── Health ───────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "4.0.0", "bot": bot_state}

@app.get("/api/health/readiness")
def readiness(workspace_id: int = 1):
    bot  = DigikalaRepricer(workspace_id, log_callback=save_log)
    diag = bot.get_auth_diagnostics()
    return {
        "status":      "ready" if diag["is_read_auth_ok"] else "degraded",
        "time":        datetime.now().isoformat(),
        "diagnostics": diag,
    }

@app.get("/api/diagnostics/auth")
def auth_diagnostics(workspace_id: int = 1):
    bot = DigikalaRepricer(workspace_id, log_callback=save_log)
    return {"status": "ok", "diagnostics": bot.get_auth_diagnostics()}

@app.get("/api/metrics")
def metrics(workspace_id: int = 1):
    bot = DigikalaRepricer(workspace_id, log_callback=save_log)
    return {"status": "ok", "metrics": bot.get_runtime_metrics()}


# ─── Products ─────────────────────────────────────────────────────────────────
@app.get("/api/products")
def get_products(workspace_id: int = 1):
    bot           = DigikalaRepricer(workspace_id)
    saved_configs = _load_config()

    all_variants, page, total_pages = [], 1, 1
    while page <= total_pages:
        res = bot.get_my_variants(page)
        if not res["success"]:
            break
        total_pages = res["total_pages"]
        for item in res["variants"]:
            vid  = str(item["variant_id"])
            conf = saved_configs.get(vid, {})
            item["min_price"]  = conf.get("min_price", "")
            item["max_price"]  = conf.get("max_price", "")
            item["enabled"]    = conf.get("enabled", True)
            item["strategy"]   = conf.get("strategy", "aggressive")
            item["step"]       = conf.get("step", None)
            item["has_config"] = vid in saved_configs
            all_variants.append(item)
        page += 1

    return {
        "variants":   all_variants,
        "total":      len(all_variants),
        "configured": sum(1 for v in all_variants if v["has_config"]),
    }


# ─── Competitors (از API عمومی) ───────────────────────────────────────────────
@app.post("/api/competitors")
def get_competitors(data: CompetitorPriceModel):
    """
    دریافت قیمت رقبا از API عمومی دیجی‌کالا.
    product_id: شناسه عددی محصول (عدد بعد از dkp-)
    """
    bot        = DigikalaRepricer(data.workspace_id)
    price, alone = bot.get_competitor_prices(data.product_id, data.my_seller_id)
    return {
        "product_id":            data.product_id,
        "lowest_competitor_price": price,
        "alone_in_market":       alone,
    }


# ─── Config ───────────────────────────────────────────────────────────────────
@app.post("/api/config")
def save_config(data: ConfigModel):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data.configs, f, ensure_ascii=False, indent=4)
    return {"status": "success", "saved_count": len(data.configs)}

@app.get("/api/config")
def get_config():
    return _load_config()

@app.put("/api/config/{variant_id}")
def update_variant_config(variant_id: str, data: VariantConfigModel):
    """
    آپدیت config یک تنوع خاص.
    فقط فیلدهای ارسال‌شده آپدیت می‌شوند.
    """
    configs = _load_config()
    existing = configs.get(variant_id, {})

    updated = {**existing}
    if data.min_price is not None:
        updated["min_price"] = data.min_price
    if data.max_price is not None:
        updated["max_price"] = data.max_price
    updated["enabled"]  = data.enabled
    updated["strategy"] = data.strategy
    if data.step is not None:
        updated["step"] = data.step
    if data.product_id is not None:
        updated["product_id"] = data.product_id

    configs[variant_id] = updated
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(configs, f, ensure_ascii=False, indent=4)

    return {"status": "success", "variant_id": variant_id, "config": updated}

@app.patch("/api/config/{variant_id}/toggle")
def toggle_variant(variant_id: str, enabled: bool):
    """روشن/خاموش کردن ربات برای یک تنوع خاص"""
    configs = _load_config()
    if variant_id not in configs:
        raise HTTPException(404, f"تنوع {variant_id} در config نیست")
    configs[variant_id]["enabled"] = enabled
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(configs, f, ensure_ascii=False, indent=4)
    return {"status": "success", "variant_id": variant_id, "enabled": enabled}

@app.patch("/api/config/{variant_id}/strategy")
def set_variant_strategy(variant_id: str, strategy: str):
    """تغییر استراتژی یک تنوع خاص"""
    valid = [s["key"] for s in STRATEGY_INFO]
    if strategy not in valid:
        raise HTTPException(400, f"استراتژی نامعتبر. مقادیر مجاز: {valid}")
    configs = _load_config()
    if variant_id not in configs:
        raise HTTPException(404, f"تنوع {variant_id} در config نیست")
    configs[variant_id]["strategy"] = strategy
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(configs, f, ensure_ascii=False, indent=4)
    return {"status": "success", "variant_id": variant_id, "strategy": strategy}


# ─── Settings ─────────────────────────────────────────────────────────────────
@app.get("/api/settings")
def get_settings():
    return {
        "settings":       _load_settings(),
        "strategies":     STRATEGY_INFO,
        "presets":        PRESET_FORMULAS,
        "variable_help":  FORMULA_VARIABLES_HELP,
    }

@app.post("/api/settings")
def save_settings(data: SettingsModel):
    if data.request_delay_min > data.request_delay_max:
        raise HTTPException(400, "تاخیر کمینه نباید بیشتر از بیشینه باشد")
    if data.rate_limit_backoff_base < 5:
        raise HTTPException(400, "backoff نباید کمتر از ۵ ثانیه باشد")
    if data.variant_cooldown_seconds < 0:
        raise HTTPException(400, "cooldown نباید منفی باشد")
    if data.default_step < 100:
        raise HTTPException(400, "گام نباید کمتر از ۱۰۰ تومان باشد")
    if data.rate_limit_pause_seconds < 30:
        raise HTTPException(400, "rate_limit_pause باید حداقل ۳۰ ثانیه باشد")

    settings = data.model_dump()
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)
    return {"status": "success", "settings": settings}


# ─── Formula ──────────────────────────────────────────────────────────────────
@app.post("/api/formula/test")
def formula_test(data: FormulaTestModel):
    defaults = {
        "competitor_price": 100000, "reference_price": 150000,
        "current_price": 100000,    "step_price": 1000,
        "min_price": 70000,         "cost": 60000,
        "buy_box_price": 95000,
    }
    sample = {**defaults, **data.sample_values}
    return test_formula(data.formula, sample)

@app.get("/api/formula/presets")
def formula_presets():
    return {"presets": PRESET_FORMULAS, "variable_help": FORMULA_VARIABLES_HELP}

@app.post("/api/bot/apply_min_formula")
def apply_min_formula(data: ApplyMinFormulaModel):
    bot     = DigikalaRepricer(data.workspace_id, log_callback=save_log)
    configs = _load_config()

    all_variants, page, total_pages = [], 1, 1
    while page <= total_pages:
        res = bot.get_my_variants(page)
        if not res["success"]:
            break
        total_pages = res["total_pages"]
        all_variants.extend(res["variants"])
        page += 1

    updated, errors = {}, {}
    for item in all_variants:
        vid = str(item["variant_id"])
        ref = int(item.get("reference_price") or item.get("current_price") or 0)
        cur = int(item.get("current_price") or 0)
        try:
            min_p = calculate_min_price(data.formula, ref, cur, data.step_price)
            updated[vid] = {**configs.get(vid, {}), "min_price": min_p}
        except ValueError as e:
            errors[vid] = str(e)

    if updated:
        merged = {**configs, **updated}
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=4)

    return {
        "status":        "success",
        "updated_count": len(updated),
        "error_count":   len(errors),
        "errors":        errors,
    }


# ─── Bot control ──────────────────────────────────────────────────────────────
@app.post("/api/bot/start")
def start_bot(data: BotStartModel, background_tasks: BackgroundTasks):
    if bot_state["is_running"]:
        return {"status": "already_running", "state": bot_state}

    bot_state.update({
        "is_running":      True,
        "workspace_id":    data.workspace_id,
        "started_at":      datetime.now().isoformat(),
        "cycle_count":     0,
        "total_updates":   0,
        "rate_limit_hits": 0,
    })
    background_tasks.add_task(run_bot_loop, data.workspace_id, data.cycle_delay)
    settings = _load_settings()
    save_log(
        f"▶️ ربات روشن شد | workspace={data.workspace_id} | "
        f"تاخیر={data.cycle_delay}s | "
        f"استراتژی پیش‌فرض={settings.get('default_strategy','aggressive')} | "
        f"گام پیش‌فرض={settings.get('default_step',1000):,}"
    )
    return {"status": "running", "state": bot_state}

@app.post("/api/bot/stop")
def stop_bot():
    bot_state["is_running"] = False
    save_log("⏹ ربات متوقف شد.")
    return {"status": "stopped"}

@app.post("/api/bot/test_price")
def test_price(data: TestPriceModel):
    bot = DigikalaRepricer(data.workspace_id, log_callback=save_log)
    return bot.update_my_price(data.variant_id, data.test_price)

@app.post("/api/bot/discover_bounds")
def discover_bounds(data: DiscoverModel):
    bot = DigikalaRepricer(data.workspace_id, log_callback=save_log)
    return bot.discover_price_bounds(
        str(data.variant_id),
        data.reference_price,
        data.current_price,
    )


# ─── Strategies ───────────────────────────────────────────────────────────────
@app.get("/api/strategies")
def get_strategies():
    return {"strategies": STRATEGY_INFO}


# ─── Logs ─────────────────────────────────────────────────────────────────────
@app.get("/api/logs")
def get_logs(limit: int = 200):
    with logs_lock:
        recent = logs[-limit:]
    return {
        "logs":       [l["msg"] for l in reversed(recent)],
        "is_running": bot_state["is_running"],
        "bot_state":  bot_state,
    }

@app.delete("/api/logs")
def clear_logs():
    with logs_lock:
        logs.clear()
    return {"status": "cleared"}

@app.get("/api/stats")
def get_stats():
    with logs_lock:
        total_logs = len(logs)
    return {"bot": bot_state, "total_log_entries": total_logs}