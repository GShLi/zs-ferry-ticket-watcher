import json
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.database import get_db
from src.models import PortsCache, SystemUser, Setting
from src.auth import get_current_user
from src.schemas import PortsCacheOut, PortRouteOut

router = APIRouter(prefix="/api/ports", tags=["ports"])

PORTS_API_URL = "https://pc.ssky123.com/api/v2/line/port/all"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://pc.ssky123.com/online_booking_pc/",
    "Origin": "https://pc.ssky123.com",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


def _fetch_and_cache_ports(db: Session) -> list[dict]:
    """从官网 API 拉取航线列表，写入缓存表，返回 list[dict]"""
    import requests  # 延迟导入，避免启动时报错

    try:
        resp = requests.get(PORTS_API_URL, headers=BROWSER_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"获取航线数据失败：{e}")

    if data.get("code") != 200:
        raise RuntimeError(f"API 返回错误：{data.get('message')}")

    line_list = data["data"]["lineList"]

    # 清空旧缓存，写入新数据
    db.query(PortsCache).delete()
    now = datetime.now()
    for item in line_list:
        db.add(PortsCache(
            start_port_num=item["startPortNum"],
            start_port_name=item["startPortName"],
            end_port_num=item["endPortNum"],
            end_port_name=item["endPortName"],
            updated_at=now,
        ))
    db.commit()
    return line_list


@router.get("/", response_model=PortsCacheOut)
def get_ports(
    refresh: bool = False,
    db: Session = Depends(get_db),
    _: SystemUser = Depends(get_current_user),
):
    """
    获取航线缓存。传 ?refresh=true 强制从官网重新拉取。
    """
    if refresh or db.query(PortsCache).count() == 0:
        _fetch_and_cache_ports(db)

    rows = db.query(PortsCache).all()
    updated_at = rows[0].updated_at if rows else None

    routes = [
        PortRouteOut(
            start_port_num=r.start_port_num,
            start_port_name=r.start_port_name,
            end_port_num=r.end_port_num,
            end_port_name=r.end_port_name,
        )
        for r in rows
    ]
    return PortsCacheOut(routes=routes, updated_at=updated_at)
