"""Cookie / localStorage 会话持久化与恢复"""
import json
import os
from datetime import datetime, timedelta
from typing import Optional

from cryptography.fernet import Fernet
from selenium.webdriver.remote.webdriver import WebDriver
from sqlalchemy.orm import Session

from src.models import FerryAccount

# Fernet key，生产环境应从环境变量或文件读取
_FERNET_KEY_ENV = "FERRY_FERNET_KEY"
_FERNET_KEY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".fernet_key")


def _get_or_create_fernet_key() -> bytes:
    key = os.environ.get(_FERNET_KEY_ENV)
    if key:
        return key.encode()
    if os.path.exists(_FERNET_KEY_FILE):
        with open(_FERNET_KEY_FILE, "rb") as f:
            return f.read().strip()
    # 首次运行：生成并保存
    new_key = Fernet.generate_key()
    with open(_FERNET_KEY_FILE, "wb") as f:
        f.write(new_key)
    return new_key


_fernet = Fernet(_get_or_create_fernet_key())


def encrypt_password(plain: str) -> str:
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_password(enc: str) -> str:
    return _fernet.decrypt(enc.encode()).decode()


# ─── 会话保存 ──────────────────────────────────────────────

def save_session(driver: WebDriver, account: FerryAccount, db: Session):
    """登录成功后，把 cookies 和 localStorage 存入数据库"""
    cookies = driver.get_cookies()
    account.cookies_json = json.dumps(cookies, ensure_ascii=False)

    ls_raw = driver.execute_script("return JSON.stringify(localStorage)")
    account.local_storage_json = ls_raw or "{}"

    # 估算过期时间：取 cookie expiry 最小值
    expiries = [c["expiry"] for c in cookies if "expiry" in c]
    if expiries:
        account.session_expires_at = datetime.fromtimestamp(min(expiries))
    else:
        account.session_expires_at = datetime.now() + timedelta(hours=24)

    account.last_login_at = datetime.now()
    db.commit()


# ─── 会话恢复 ──────────────────────────────────────────────

def restore_session(driver: WebDriver, account: FerryAccount):
    """将数据库中的 cookies 和 localStorage 注入到 driver"""
    # 先打开目标域，使 cookie domain 生效
    driver.get("https://pc.ssky123.com/online_booking_pc/#/index")

    cookies: list = json.loads(account.cookies_json or "[]")
    for cookie in cookies:
        # selenium 不接受 sameSite=None 等特殊值，安全忽略异常
        try:
            # 去除 selenium 不支持的字段
            safe = {k: v for k, v in cookie.items() if k in
                    ("name", "value", "domain", "path", "expiry", "secure", "httpOnly")}
            driver.add_cookie(safe)
        except Exception:
            pass

    # 注入 localStorage
    ls: dict = json.loads(account.local_storage_json or "{}")
    if ls:
        script = "".join(
            f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)});"
            for k, v in ls.items()
        )
        driver.execute_script(script)

    # 刷新页面使 cookie 生效
    driver.refresh()


# ─── 会话验证 ──────────────────────────────────────────────

def is_session_valid(account: FerryAccount) -> bool:
    """快速检查：过期时间是否仍在未来"""
    if not account.session_expires_at:
        return False
    return account.session_expires_at > datetime.now()


def verify_session_online(driver: WebDriver) -> bool:
    """
    检查当前页面是否已登录。
    登录成功后 header 中会有 <div class="index__titlename"><p>手机号</p></div>。
    返回 True 表示登录态有效。
    """
    try:
        from selenium.webdriver.common.by import By
        els = driver.find_elements(By.XPATH, "//div[@class='index__titlename']")
        return len(els) > 0 and bool(els[0].text.strip())
    except Exception:
        return False
