"""Bark 推送通知"""
import requests

from src.database import SessionLocal
from src.models import Setting

DEFAULT_SERVER = "https://api.day.app"


def _get_bark_config() -> tuple[list[str], str]:
    """返回 (keys列表, server)，keys 支持换行/逗号分隔的多个 Key。"""
    db = SessionLocal()
    try:
        key_row = db.query(Setting).filter_by(key="bark_key").first()
        srv_row = db.query(Setting).filter_by(key="bark_server").first()
        raw = key_row.value if key_row else ""
        server = (srv_row.value if srv_row else "") or DEFAULT_SERVER
        # 支持换行或逗号分隔
        keys = [k.strip() for k in raw.replace(",", "\n").splitlines() if k.strip()]
        return keys, server
    finally:
        db.close()


def _send_to_key(key: str, server: str, payload: dict) -> bool:
    endpoint = f"{server.rstrip('/')}/{key}"
    try:
        resp = requests.post(endpoint, json=payload, timeout=8)
        return resp.status_code == 200
    except Exception:
        return False


def send_bark(title: str, body: str, url: str = "", sound: str = "birdsong") -> bool:
    """向所有已配置的 Bark Key 发送通知，至少一个成功则返回 True。"""
    keys, bark_server = _get_bark_config()
    if not keys:
        return False

    payload = {"title": title, "body": body, "sound": sound}
    if url:
        payload["url"] = url

    results = [_send_to_key(k, bark_server, payload) for k in keys]
    return any(results)


def notify_booked(order_id: str, route: str, travel_date: str, payment_expire_at: str = ""):
    if payment_expire_at:
        pay_line = f"请在 {payment_expire_at} 前完成支付（约5分钟）"
    else:
        pay_line = "请在5分钟内完成支付"
    send_bark(
        title="🎫 抢票成功！",
        body=f"{route} {travel_date}\n订单号：{order_id}\n{pay_line}",
        sound="success",
    )


def notify_failed(task_id: int, reason: str):
    send_bark(
        title="❌ 抢票失败",
        body=f"任务 #{task_id} 失败：{reason[:100]}",
        sound="alarm",
    )
