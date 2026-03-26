import json
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
import time

class ManualCookieManager:
    def __init__(self, sessions_dir: Path):
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(exist_ok=True)
    
    def get_cookie_path(self, workspace_id: int) -> Path:
        return self.sessions_dir / f"ws_{workspace_id}_cookies.json"
    
    def check_cookie_validity(self, workspace_id: int) -> Dict:
        """بررسی وجود فایل کوکی"""
        cookie_path = self.get_cookie_path(workspace_id)
        
        if not cookie_path.exists():
            return {
                "valid": False,
                "status": "not_found",
                "message": "فایل کوکی یافت نشد"
            }
        
        try:
            with open(cookie_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            cookies = data.get('cookies', [])
            if not cookies:
                 return {"valid": False, "status": "empty", "message": "فایل خالی است"}

            created_at = data.get('created_at', '')
            age_hours = 0
            if created_at:
                try:
                    dt_created = datetime.fromisoformat(created_at)
                    age_hours = (datetime.now() - dt_created).total_seconds() / 3600
                except:
                    pass

            return {
                "valid": True,
                "created_at": created_at,
                "age_hours": age_hours,
                "cookie_count": len(cookies),
                "status": "valid"
            }
            
        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "status": "invalid"
            }

    def manual_login_flow(self, workspace_id: int, email: str, timeout_seconds: int = 60) -> dict:
        """باز کردن مرورگر برای لاگین دستی"""
        from selenium import webdriver
        
        driver = None
        try:
            driver = webdriver.Chrome()
            driver.get("https://seller.digikala.com/")
            print(f"⏳ پنجره لاگین برای پنل {workspace_id} ({email}) باز شد.")
            print(f"شما {timeout_seconds} ثانیه فرصت دارید تا اطلاعات ورود را وارد کنید...")
            
            time.sleep(timeout_seconds)
            
            cookies = driver.get_cookies()
            if cookies:
                self.save_cookies(workspace_id, cookies)
                print("✅ کوکی‌ها با موفقیت استخراج و ذخیره شدند.")
                return {"status": "success", "cookie_count": len(cookies)}
            else:
                print("❌ کوکی یافت نشد.")
                return {"status": "failed", "message": "هیچ کوکی یافت نشد"}
                
        except Exception as e:
            print(f"⚠️ خطا در فرآیند لاگین دستی: {e}")
            return {"status": "error", "error": str(e)}
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
                
    def save_cookies(self, workspace_id: int, cookies: List[Dict]) -> bool:
        try:
            cookie_path = self.get_cookie_path(workspace_id)
            cookie_data = {
                "workspace_id": workspace_id,
                "cookies": cookies,
                "created_at": datetime.now().isoformat(),
                "count": len(cookies)
            }
            with open(cookie_path, 'w', encoding='utf-8') as f:
                json.dump(cookie_data, f, ensure_ascii=False, indent=2)
            print(f"✅ کوکی‌ها ذخیره شدند: {cookie_path}")
            return True
        except Exception as e:
            print(f"❌ خطا در ذخیره کوکی: {e}")
            return False

    def load_cookies_to_driver(self, driver, workspace_id: int) -> bool:
        """بارگذاری کوکی‌ها در درایور سلنیوم"""
        status = self.check_cookie_validity(workspace_id)
        if not status['valid']:
            return False
            
        try:
            cookie_path = self.get_cookie_path(workspace_id)
            with open(cookie_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            cookies = data.get('cookies', [])
            if not cookies:
                return False

            added_count = 0
            for cookie in cookies:
                cookie_dict = {
                    'name': cookie.get('name'),
                    'value': cookie.get('value'),
                    'domain': cookie.get('domain'),
                    'path': cookie.get('path', '/'),
                    'secure': cookie.get('secure', False)
                }
                
                if 'expiry' in cookie:
                    try:
                        cookie_dict['expiry'] = int(cookie['expiry'])
                    except:
                        pass
                
                try:
                    driver.add_cookie(cookie_dict)
                    added_count += 1
                except Exception:
                    pass
            
            print(f"🍪 {added_count} کوکی بارگذاری شد.")
            return added_count > 0
            
        except Exception as e:
            print(f"⚠️ خطا در لود کوکی: {e}")
            return False