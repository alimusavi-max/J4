from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Union, Optional
from pydantic import BaseModel
import json
import time
import threading
from pathlib import Path
from datetime import datetime
from utils.repricer_engine import DigikalaRepricer

app = FastAPI(title="Digikala Repricer API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_FILE = "repricer_config.json"

# ─── State مدیریت ربات ───────────────────────────────────────────────
bot_state = {
    "is_running": False,
    "workspace_id": 1,
    "step_price": 1000,
    "started_at": None,
    "cycle_count": 0,
    "total_updates": 0,
    "buybox_wins": 0,
}
logs = []
logs_lock = threading.Lock()

def save_log(msg):
    with logs_lock:
        logs.append({"msg": msg, "time": datetime.now().isoformat()})
        if len(logs) > 200:
            logs.pop(0)

# ─── Bot Loop ────────────────────────────────────────────────────────
def run_bot_loop(workspace_id: int, step_price: int, cycle_delay: int = 120):
    bot = DigikalaRepricer(workspace_id, log_callback=save_log)
    configs = {}

    while bot_state["is_running"]:
        # بارگذاری آخرین config در هر چرخه
        if Path(CONFIG_FILE).exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    configs = json.load(f)
            except:
                pass

        result = bot.evaluate_and_act_all(configs, step_price=step_price)

        bot_state["cycle_count"] += 1
        bot_state["total_updates"] += result.get("updated_count", 0)
        bot_state["buybox_wins"] = result.get("buybox_count", 0)

        # انتظار بین چرخه‌ها، با قابلیت توقف آنی
        for _ in range(cycle_delay):
            if not bot_state["is_running"]:
                break
            time.sleep(1)

# ─── Models ──────────────────────────────────────────────────────────
class ConfigModel(BaseModel):
    configs: dict

class BotStartModel(BaseModel):
    workspace_id: int = 1
    step_price: int = 1000
    cycle_delay: int = 120  # ثانیه بین هر چرخه

class TestPriceModel(BaseModel):
    workspace_id: int
    variant_id: str
    test_price: int

class DiscoverModel(BaseModel):
    workspace_id: int
    variant_id: Union[int, str]
    reference_price: int
    current_price: int

# ─── Endpoints ───────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0.0", "bot": bot_state}

@app.get("/api/products")
def get_products(workspace_id: int = 1):
    bot = DigikalaRepricer(workspace_id)
    saved_configs = {}
    if Path(CONFIG_FILE).exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved_configs = json.load(f)
        except:
            pass

    all_variants = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        res = bot.get_my_variants(page)
        if not res['success']:
            break
        total_pages = res['total_pages']

        for item in res['variants']:
            vid = str(item['variant_id'])
            item['min_price'] = saved_configs.get(vid, {}).get('min_price', '')
            item['max_price'] = saved_configs.get(vid, {}).get('max_price', '')
            item['has_config'] = vid in saved_configs
            all_variants.append(item)
        page += 1

    return {
        "variants": all_variants,
        "total": len(all_variants),
        "configured": sum(1 for v in all_variants if v['has_config'])
    }

@app.get("/api/competitors/{variant_id}")
def get_competitors(variant_id: str, workspace_id: int = 1):
    bot = DigikalaRepricer(workspace_id)
    price, alone = bot.get_competitor_price(variant_id)
    return {"variant_id": variant_id, "lowest_competitor_price": price, "alone_in_buybox": alone}

@app.post("/api/config")
def save_config(data: ConfigModel):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data.configs, f, ensure_ascii=False, indent=4)
    return {"status": "success", "saved_count": len(data.configs)}

@app.get("/api/config")
def get_config():
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

@app.post("/api/bot/start")
def start_bot(data: BotStartModel, background_tasks: BackgroundTasks):
    if bot_state["is_running"]:
        return {"status": "already_running", "state": bot_state}

    bot_state["is_running"] = True
    bot_state["workspace_id"] = data.workspace_id
    bot_state["step_price"] = data.step_price
    bot_state["started_at"] = datetime.now().isoformat()
    bot_state["cycle_count"] = 0
    bot_state["total_updates"] = 0

    background_tasks.add_task(run_bot_loop, data.workspace_id, data.step_price, data.cycle_delay)
    save_log(f"▶️ ربات روشن شد | workspace={data.workspace_id} | step={data.step_price:,} | تاخیر={data.cycle_delay}s")
    return {"status": "running", "state": bot_state}

@app.post("/api/bot/stop")
def stop_bot():
    bot_state["is_running"] = False
    save_log("⏹ ربات متوقف شد.")
    return {"status": "stopped"}

@app.get("/api/logs")
def get_logs(limit: int = 100):
    with logs_lock:
        recent = logs[-limit:]
    return {
        "logs": [l["msg"] for l in reversed(recent)],
        "is_running": bot_state["is_running"],
        "bot_state": bot_state
    }

@app.delete("/api/logs")
def clear_logs():
    with logs_lock:
        logs.clear()
    return {"status": "cleared"}

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
        data.current_price
    )
    return result

@app.get("/api/stats")
def get_stats():
    with logs_lock:
        total_logs = len(logs)
    return {
        "bot": bot_state,
        "total_log_entries": total_logs
    }