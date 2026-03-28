from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Union, Optional, Any
from pydantic import BaseModel
import json
import time
import threading
from pathlib import Path
from datetime import datetime
from utils.repricer_engine import DigikalaRepricer
from utils.formula_engine import test_formula, calculate_min_price, PRESET_FORMULAS, FORMULA_VARIABLES_HELP

app = FastAPI(title="Digikala Repricer API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_FILE   = "repricer_config.json"
SETTINGS_FILE = "repricer_settings.json"

DEFAULT_SETTINGS = {
    "lead_time":               2,
    "shipping_type":           "seller",
    "max_per_order":           4,
    "request_delay_min":       3.0,
    "request_delay_max":       6.0,
    "rate_limit_backoff_base": 15,
    "max_retries":             3,
    "buybox_formula":          "competitor_price - step_price",
    "min_price_formula":       "",
    "auto_apply_min_price":    False,
    "strategy_mode":           "aggressive",
}

# ─── State مدیریت ربات ───────────────────────────────────────────────
bot_state = {
    "is_running":    False,
    "workspace_id":  1,
    "step_price":    1000,
    "started_at":    None,
    "cycle_count":   0,
    "total_updates": 0,
    "buybox_wins":   0,
    "rate_limit_hits": 0,
}
logs = []
logs_lock = threading.Lock()


def save_log(msg):
    with logs_lock:
        logs.append({"msg": msg, "time": datetime.now().isoformat()})
        if len(logs) > 300:
            logs.pop(0)


def _load_config() -> dict:
    if Path(CONFIG_FILE).exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _load_settings() -> dict:
    if Path(SETTINGS_FILE).exists():
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            return {**DEFAULT_SETTINGS, **saved}
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


# ─── Bot Loop ────────────────────────────────────────────────────────
def run_bot_loop(workspace_id: int, step_price: int, cycle_delay: int = 120):
    bot = DigikalaRepricer(workspace_id, log_callback=save_log)

    while bot_state["is_running"]:
        configs = _load_config()
        result = bot.evaluate_and_act_all(configs, step_price=step_price)

        bot_state["cycle_count"]    += 1
        bot_state["total_updates"]  += result.get("updated_count", 0)
        bot_state["buybox_wins"]     = result.get("buybox_count", 0)
        bot_state["rate_limit_hits"] += result.get("rate_limit_hits", 0)

        for _ in range(cycle_delay):
            if not bot_state["is_running"]:
                break
            time.sleep(1)


# ─── Pydantic Models ─────────────────────────────────────────────────
class ConfigModel(BaseModel):
    configs: dict

class BotStartModel(BaseModel):
    workspace_id: int = 1
    step_price:   int = 1000
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
    lead_time:               int   = 2
    shipping_type:           str   = "seller"
    max_per_order:           int   = 4
    request_delay_min:       float = 3.0
    request_delay_max:       float = 6.0
    rate_limit_backoff_base: int   = 15
    max_retries:             int   = 3
    buybox_formula:          str   = "competitor_price - step_price"
    min_price_formula:       str   = ""
    auto_apply_min_price:    bool  = False
    strategy_mode:           str   = "aggressive"

class FormulaTestModel(BaseModel):
    formula:       str
    formula_type:  str = "buybox"   # buybox | min_price
    sample_values: dict = {}

class ApplyMinFormulaModel(BaseModel):
    workspace_id: int = 1
    formula:      str
    step_price:   int = 1000


# ─── Health ──────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "3.0.0", "bot": bot_state}


# ─── Products ────────────────────────────────────────────────────────
@app.get("/api/products")
def get_products(workspace_id: int = 1):
    bot = DigikalaRepricer(workspace_id)
    saved_configs = _load_config()

    all_variants = []
    page, total_pages = 1, 1
    while page <= total_pages:
        res = bot.get_my_variants(page)
        if not res['success']:
            break
        total_pages = res['total_pages']
        for item in res['variants']:
            vid = str(item['variant_id'])
            item['min_price']  = saved_configs.get(vid, {}).get('min_price', '')
            item['max_price']  = saved_configs.get(vid, {}).get('max_price', '')
            item['has_config'] = vid in saved_configs
            all_variants.append(item)
        page += 1

    return {
        "variants":   all_variants,
        "total":      len(all_variants),
        "configured": sum(1 for v in all_variants if v['has_config']),
    }


# ─── Competitors ─────────────────────────────────────────────────────
@app.get("/api/competitors/{variant_id}")
def get_competitors(variant_id: str, workspace_id: int = 1):
    bot = DigikalaRepricer(workspace_id)
    price, alone = bot.get_competitor_price(variant_id)
    return {
        "variant_id": variant_id,
        "lowest_competitor_price": price,
        "alone_in_buybox": alone,
    }


# ─── Config ──────────────────────────────────────────────────────────
@app.post("/api/config")
def save_config(data: ConfigModel):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data.configs, f, ensure_ascii=False, indent=4)
    return {"status": "success", "saved_count": len(data.configs)}

@app.get("/api/config")
def get_config():
    return _load_config()


# ─── Settings ────────────────────────────────────────────────────────
@app.get("/api/settings")
def get_settings():
    settings = _load_settings()
    return {
        "settings":      settings,
        "presets":        PRESET_FORMULAS,
        "variable_help":  FORMULA_VARIABLES_HELP,
    }

@app.post("/api/settings")
def save_settings(data: SettingsModel):
    # اعتبارسنجی delay منطقی
    if data.request_delay_min > data.request_delay_max:
        raise HTTPException(400, "تاخیر کمینه نباید بیشتر از بیشینه باشد")
    if data.rate_limit_backoff_base < 5:
        raise HTTPException(400, "backoff نباید کمتر از ۵ ثانیه باشد")

    settings = data.model_dump()
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)
    return {"status": "success", "settings": settings}


# ─── Formula Test ─────────────────────────────────────────────────────
@app.post("/api/formula/test")
def formula_test(data: FormulaTestModel):
    """تست فرمول با مقادیر نمونه"""
    defaults = {
        "competitor_price": 100000,
        "reference_price":  150000,
        "current_price":    100000,
        "step_price":       1000,
        "min_price":        70000,
        "cost":             60000,
        "buy_box_price":    95000,
    }
    sample = {**defaults, **data.sample_values}
    result = test_formula(data.formula, sample)
    return result

@app.get("/api/formula/presets")
def formula_presets():
    return {"presets": PRESET_FORMULAS, "variable_help": FORMULA_VARIABLES_HELP}


# ─── Apply Min Price Formula ──────────────────────────────────────────
@app.post("/api/bot/apply_min_formula")
def apply_min_formula(data: ApplyMinFormulaModel):
    """
    اعمال فرمول کف قیمت به همه محصولات و ذخیره در config
    قیمت دیجی‌کالا تغییر نمی‌کند - فقط config کف ذخیره می‌شود
    """
    bot = DigikalaRepricer(data.workspace_id, log_callback=save_log)
    current_configs = _load_config()

    result = bot.apply_min_price_formula_to_all(
        current_configs, data.formula, data.step_price
    )

    if result["updated"]:
        merged = {**current_configs, **result["updated"]}
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(merged, f, ensure_ascii=False, indent=4)

    return {
        "status":        "success",
        "updated_count": len(result["updated"]),
        "error_count":   len(result["errors"]),
        "errors":        result["errors"],
    }


# ─── Bot Control ─────────────────────────────────────────────────────
@app.post("/api/bot/start")
def start_bot(data: BotStartModel, background_tasks: BackgroundTasks):
    if bot_state["is_running"]:
        return {"status": "already_running", "state": bot_state}

    bot_state.update({
        "is_running":      True,
        "workspace_id":    data.workspace_id,
        "step_price":      data.step_price,
        "started_at":      datetime.now().isoformat(),
        "cycle_count":     0,
        "total_updates":   0,
        "rate_limit_hits": 0,
    })
    background_tasks.add_task(run_bot_loop, data.workspace_id, data.step_price, data.cycle_delay)
    settings = _load_settings()
    save_log(
        f"▶️ ربات روشن شد | workspace={data.workspace_id} | "
        f"step={data.step_price:,} | تاخیر={data.cycle_delay}s | "
        f"استراتژی={settings.get('strategy_mode','aggressive')}"
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
    result = bot.update_my_price(data.variant_id, data.test_price)
    return result

@app.post("/api/bot/discover_bounds")
def discover_bounds(data: DiscoverModel):
    bot = DigikalaRepricer(data.workspace_id, log_callback=save_log)
    result = bot.discover_price_bounds(
        str(data.variant_id),
        data.reference_price,
        data.current_price,
    )
    return result


# ─── Logs ────────────────────────────────────────────────────────────
@app.get("/api/logs")
def get_logs(limit: int = 150):
    with logs_lock:
        recent = logs[-limit:]
    return {
        "logs":      [l["msg"] for l in reversed(recent)],
        "is_running": bot_state["is_running"],
        "bot_state":  bot_state,
    }

@app.delete("/api/logs")
def clear_logs():
    with logs_lock:
        logs.clear()
    return {"status": "cleared"}


# ─── Stats ───────────────────────────────────────────────────────────
@app.get("/api/stats")
def get_stats():
    with logs_lock:
        total_logs = len(logs)
    return {"bot": bot_state, "total_log_entries": total_logs}