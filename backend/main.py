from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import Union
from pydantic import BaseModel
import json
import time
from pathlib import Path
from utils.repricer_engine import DigikalaRepricer

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_FILE = "repricer_config.json"
bot_is_running = False
logs = []

def save_log(msg):
    logs.append(msg)
    if len(logs) > 50: logs.pop(0)

def run_bot_loop(workspace_id: int, step_price: int):
    global bot_is_running
    bot = DigikalaRepricer(workspace_id, log_callback=save_log)
    configs = {}
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            configs = json.load(f)
            
    while bot_is_running:
        bot.evaluate_and_act_all(configs, step_price=step_price)
        for _ in range(120):
            if not bot_is_running: break
            time.sleep(1)

class ConfigModel(BaseModel):
    configs: dict

class TestPriceModel(BaseModel):
    workspace_id: int
    variant_id: str
    test_price: int

class DiscoverModel(BaseModel):
    workspace_id: int
    variant_id: Union[int, str]
    reference_price: int
    current_price: int

@app.get("/api/products")
def get_products(workspace_id: int = 1):
    bot = DigikalaRepricer(workspace_id)
    saved_configs = {}
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            saved_configs = json.load(f)

    all_variants = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        res = bot.get_my_variants(page)
        if not res['success']: break
        total_pages = res['total_pages']
        
        for item in res['variants']:
            vid = str(item['variant_id'])
            item['min_price'] = saved_configs.get(vid, {}).get('min_price', '')
            item['max_price'] = saved_configs.get(vid, {}).get('max_price', '')
            all_variants.append(item)
        page += 1
    return {"variants": all_variants}

@app.post("/api/config")
def save_config(data: ConfigModel):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data.configs, f, ensure_ascii=False, indent=4)
    return {"status": "success"}

@app.post("/api/bot/start")
def start_bot(workspace_id: int = 1, step_price: int = 1000, background_tasks: BackgroundTasks = None):
    global bot_is_running
    if not bot_is_running:
        bot_is_running = True
        background_tasks.add_task(run_bot_loop, workspace_id, step_price)
        save_log("▶️ ربات روشن شد.")
    return {"status": "running"}

@app.post("/api/bot/stop")
def stop_bot():
    global bot_is_running
    bot_is_running = False
    save_log("⏹ ربات متوقف شد.")
    return {"status": "stopped"}

@app.get("/api/logs")
def get_logs():
    return {"logs": logs, "is_running": bot_is_running}

@app.post("/api/bot/test_price")
def test_price(data: TestPriceModel):
    bot = DigikalaRepricer(data.workspace_id, log_callback=save_log)
    result = bot.update_my_price(data.variant_id, data.test_price)
    # بازگردانی امنیتی
    bot.update_my_price(data.variant_id, data.test_price, silent=True)
    return result

@app.post("/api/bot/discover_bounds")
def discover_bounds(data: DiscoverModel):
    bot = DigikalaRepricer(data.workspace_id, log_callback=save_log)
    result = bot.discover_price_bounds(data.variant_id, data.reference_price, data.current_price)
    return result