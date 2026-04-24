"""
直接调用 pc.ssky123.com REST API 的爬虫后端。
无需浏览器，速度快，适合在 Selenium Grid 不可用时使用。

认证协议（从 HAR 逆向）：
  - 请求头 token:          登录后返回的 ssky_user_xxx 字符串
  - 请求头 authentication: {unix_timestamp_seconds}{userId}  （两者直接拼接）
"""
import json
import time as _time
from datetime import datetime, timedelta
from typing import Optional

import requests
from sqlalchemy.orm import Session

from src.crawler.base import CrawlerBackend
from src.crawler.session import decrypt_password
from src.models import FerryAccount, Passenger, Vehicle

BASE_URL = "https://pc.ssky123.com/api/v2"
_SITE_HOME = "https://pc.ssky123.com/"
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://pc.ssky123.com/",
    "Origin": "https://pc.ssky123.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


def _auth_header(user_id: int) -> str:
    """生成 authentication 头：{timestamp秒}{userId}"""
    ts = int(_time.time())
    return f"{ts}{user_id}"


class ApiBackend(CrawlerBackend):
    """通过 HTTP API 直接与购票系统交互，无需 Selenium"""

    # ── 内部工具 ───────────────────────────────────────────

    def _load_session(self, account: FerryAccount) -> tuple[Optional[str], int]:
        """从 local_storage_json 中读取 token 和 userId，不存在返回 (None, 0)"""
        try:
            ls = json.loads(account.local_storage_json or "{}")
            return ls.get("token"), ls.get("userId", 0)
        except Exception:
            return None, 0

    def _save_session(self, account: FerryAccount, token: str, user_id: int, db: Session,
                      cookies: dict = None):
        """把 token/userId 序列化进 local_storage_json，并持久化 Cookie"""
        ls = {"token": token, "userId": user_id}
        account.local_storage_json = json.dumps(ls)
        if cookies is not None:
            account.cookies_json = json.dumps(cookies)
        account.session_expires_at = datetime.now() + timedelta(days=7)
        account.last_login_at = datetime.now()
        db.commit()

    def _make_session(self, account: FerryAccount) -> requests.Session:
        """创建携带已保存 Cookie 的 requests.Session"""
        s = requests.Session()
        try:
            saved = json.loads(account.cookies_json or "[]")
            # cookies_json 可能是 list（Selenium 格式）或 dict（API 格式）
            if isinstance(saved, list):
                for c in saved:
                    if isinstance(c, dict) and c.get("name"):
                        s.cookies.set(c["name"], c.get("value", ""),
                                      domain=c.get("domain", ""), path=c.get("path", "/"))
            elif isinstance(saved, dict):
                for name, value in saved.items():
                    s.cookies.set(name, value)
        except Exception:
            pass
        return s

    def _headers(self, token: Optional[str], user_id: int) -> dict:
        h = dict(_DEFAULT_HEADERS)
        h["token"] = token or "undefined"
        h["authentication"] = _auth_header(user_id)
        return h

    def _get(self, path: str, token: str, user_id: int, account: FerryAccount = None, **kwargs) -> dict:
        sess = self._make_session(account) if account else requests.Session()
        resp = sess.get(
            BASE_URL + path,
            headers=self._headers(token, user_id),
            timeout=15,
            **kwargs,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, token: str, user_id: int, data: dict = None, params: dict = None,
              extra_headers: dict = None, account: FerryAccount = None) -> dict:
        sess = self._make_session(account) if account else requests.Session()
        h = self._headers(token, user_id)
        if extra_headers:
            h.update(extra_headers)
        resp = sess.post(
            BASE_URL + path,
            headers=h,
            json=data,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    # ── 认证 ──────────────────────────────────────────────

    def login(self, account: FerryAccount, db: Session) -> str:
        password = decrypt_password(account.password_enc)
        sess = requests.Session()
        # 先访问主页，触发服务器下发 acw_tc 等 WAF Cookie
        try:
            home_headers = {
                "User-Agent": _DEFAULT_HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "sec-ch-ua": _DEFAULT_HEADERS["sec-ch-ua"],
                "sec-ch-ua-mobile": _DEFAULT_HEADERS["sec-ch-ua-mobile"],
                "sec-ch-ua-platform": _DEFAULT_HEADERS["sec-ch-ua-platform"],
            }
            sess.get(_SITE_HOME, headers=home_headers, timeout=10)
        except Exception:
            pass  # 获取 WAF Cookie 失败时仍尝试登录
        h = self._headers(None, 0)
        resp = sess.post(
            BASE_URL + "/user/passLogin",
            headers=h,
            params={
                "phoneNum": account.phone,
                "passwd": password,
                "deviceType": "3",
            },
            timeout=15,
        )
        resp.raise_for_status()
        resp_data = resp.json()
        if resp_data.get("code") != 200:
            raise RuntimeError(f"登录失败：{resp_data.get('message')}")
        d = resp_data["data"]
        token = d["token"]
        user_id = d["userId"]
        # 持久化登录后 Session 中全部 Cookie，保留 domain/path 以供后续请求正确匹配
        cookies_list = [
            {"name": c.name, "value": c.value,
             "domain": c.domain or "", "path": c.path or "/"}
            for c in sess.cookies
        ]
        self._save_session(account, token, user_id, db, cookies=cookies_list)
        return f"登录成功（userId={user_id}）"

    def verify_session(self, account: FerryAccount, db: Session) -> bool:
        token, user_id = self._load_session(account)
        if not token or not user_id:
            return False
        try:
            resp = self._get("/user/tokenCheck", token, user_id, account=account)
            return resp.get("code") == 200
        except Exception:
            return False

    def ensure_logged_in(self, account: FerryAccount, db: Session) -> str:
        """tokenCheck 验证会话有效性，无效则重新登录"""
        if self.verify_session(account, db):
            return "会话复用成功"
        return self.login(account, db)

    # ── 带自动重新认证的请求包装器 ──────────────────────────────
    # 流程：① tokenCheck 预检（ensure_logged_in）
    #       ② 发送请求
    #       ③ 若响应表示认证失败 → 强制重新登录 → 重试一次

    @staticmethod
    def _is_auth_failure(resp_json: dict) -> bool:
        """判断 API 响应是否为认证失败（token 过期/未登录）"""
        code = resp_json.get("code", 0)
        msg = str(resp_json.get("message") or "").lower()
        if code in (401, 403):
            return True
        return any(kw in msg for kw in ("未登录", "token", "请登录", "登录过期", "未授权"))

    def _authed_get(self, path: str, account: FerryAccount, db: Session, **kwargs) -> dict:
        """带自动重认证的 GET：预检 tokenCheck → 请求 → auth 失败则重登录重试一次"""
        self.ensure_logged_in(account, db)
        token, user_id = self._load_session(account)
        resp_json = self._get(path, token, user_id, account=account, **kwargs)
        if self._is_auth_failure(resp_json):
            print(f"[AUTH] GET {path} 返回认证失败，强制重登录...")
            self.login(account, db)
            token, user_id = self._load_session(account)
            resp_json = self._get(path, token, user_id, account=account, **kwargs)
        return resp_json

    def _authed_post(self, path: str, account: FerryAccount, db: Session,
                     data: dict = None, params: dict = None, extra_headers: dict = None) -> dict:
        """带自动重认证的 POST：预检 tokenCheck → 请求 → auth 失败则重登录重试一次"""
        self.ensure_logged_in(account, db)
        token, user_id = self._load_session(account)
        resp_json = self._post(path, token, user_id, data=data, params=params,
                               extra_headers=extra_headers, account=account)
        if self._is_auth_failure(resp_json):
            print(f"[AUTH] POST {path} 返回认证失败，强制重登录...")
            self.login(account, db)
            token, user_id = self._load_session(account)
            resp_json = self._post(path, token, user_id, data=data, params=params,
                                   extra_headers=extra_headers, account=account)
        return resp_json

    # ── 同步联系人和车辆 ────────────────────────────────────

    def sync_profile(self, account: FerryAccount, db: Session) -> dict:
        result = {
            "passengers_added": 0,
            "passengers_skipped": 0,
            "vehicles_added": 0,
            "vehicles_skipped": 0,
            "errors": [],
        }

        # 同步乘客
        try:
            resp = self._authed_get("/user/passenger/list", account, db)
            if resp.get("code") == 200:
                for p in (resp.get("data") or []):
                    _upsert_passenger(db, p, result, account.id)
        except Exception as e:
            result["errors"].append(f"同步乘客失败: {e}")

        # 同步车辆
        try:
            resp = self._authed_get("/user/vehicle/list", account, db)
            if resp.get("code") == 200:
                for v in (resp.get("data") or []):
                    _upsert_vehicle(db, v, result, account.id)
        except Exception as e:
            result["errors"].append(f"同步车辆失败: {e}")

        return result

    # ── 可售日期查询 ──────────────────────────────────────

    def get_sale_date(self, account: FerryAccount, db: Session) -> str | None:
        """返回最远可购票日期字符串 'YYYY-MM-DD'，失败返回 None"""
        try:
            resp = self._authed_get("/line/saleDate", account, db)
            if resp.get("code") == 200:
                return resp.get("data")  # e.g. "2026-04-29"
        except Exception:
            pass
        return None

    # ── 班次查询 ───────────────────────────────────────────

    def query_trips(
        self,
        account: FerryAccount,
        db: Session,
        start_port_no: int,
        end_port_no: int,
        date: str,
    ) -> list:
        resp = self._authed_post(
            "/line/ferry/enq",
            account,
            db,
            data={
                "startPortNo": start_port_no,
                "endPortNo": end_port_no,
                "startDate": date,
            },
        )
        if resp.get("code") != 200:
            raise RuntimeError(f"查询班次失败：{resp.get('message')}")
        return resp.get("data") or []

    # ── 反向推送：本地 → 远端 ─────────────────────────────

    def _fetch_remote_passengers(self, account: FerryAccount, db: Session) -> list:
        """获取远端常用旅客列表，失败时抛出异常"""
        resp = self._authed_get("/user/passenger/list", account, db)
        if resp.get("code") != 200:
            raise RuntimeError(f"获取远端旅客列表失败: {resp.get('message')}")
        return resp.get("data") or []

    def _fetch_remote_vehicles(self, account: FerryAccount, db: Session) -> list:
        """获取远端常用车辆列表，失败时抛出异常"""
        resp = self._authed_get("/user/vehicle/list", account, db)
        if resp.get("code") != 200:
            raise RuntimeError(f"获取远端车辆列表失败: {resp.get('message')}")
        return resp.get("data") or []

    def push_passenger(self, account: FerryAccount, db: Session, passenger) -> dict:
        """将本地旅客推送到远端购票账号的常用旅客列表（已存在则跳过），并将 remote_id 写回本地"""
        try:
            for remote in self._fetch_remote_passengers(account, db):
                if remote.get("credentialNum") == passenger.id_number:
                    _save_remote_id(passenger, account.id, remote["id"], db)
                    return {"code": 200, "message": "远端已存在，跳过"}
        except Exception as e:
            print(f"[PUSH] 获取远端旅客列表失败，跳过去重直接推送: {e}")
        cred_type_id = _ID_TYPE_TO_CRED_ID.get(passenger.id_type, 1)
        resp = self._authed_post("/user/passenger/save", account, db, data={
            "userId": self._load_session(account)[1],
            "passName": passenger.name,
            "passType": 1,
            "credentialTypeId": cred_type_id,
            "credentialNum": passenger.id_number,
        })
        if resp.get("code") == 200:
            try:
                for remote in self._fetch_remote_passengers(account, db):
                    if remote.get("credentialNum") == passenger.id_number:
                        _save_remote_id(passenger, account.id, remote["id"], db)
                        break
            except Exception:
                pass
        return resp

    def push_vehicle(self, account: FerryAccount, db: Session, vehicle) -> dict:
        """将本地车辆推送到远端购票账号的常用车辆列表（已存在则跳过），并将 remote_id 写回本地"""
        try:
            for remote in self._fetch_remote_vehicles(account, db):
                if remote.get("plateNum") == vehicle.plate_number:
                    _save_remote_id(vehicle, account.id, remote["id"], db)
                    return {"code": 200, "message": "远端已存在，跳过"}
        except Exception as e:
            print(f"[PUSH] 获取远端车辆列表失败，跳过去重直接推送: {e}")
        resp = self._authed_post("/user/vehicle/save", account, db, data={
            "userId": self._load_session(account)[1],
            "plateNum": vehicle.plate_number,
        })
        if resp.get("code") == 200:
            try:
                for remote in self._fetch_remote_vehicles(account, db):
                    if remote.get("plateNum") == vehicle.plate_number:
                        _save_remote_id(vehicle, account.id, remote["id"], db)
                        break
            except Exception:
                pass
        return resp

    def delete_passenger(self, account: FerryAccount, db: Session, id_number: str, id_type: str) -> dict:
        """从远端购票账号的常用旅客列表中删除指定旅客（按证件号匹配）"""
        # _fetch_remote_passengers 失败会抛出异常，由调用方（bg task）捕获并记录
        remote_list = self._fetch_remote_passengers(account, db)
        for remote in remote_list:
            if remote.get("credentialNum") == id_number:
                resp = self._authed_post("/user/passenger/delete", account, db,
                                         data={"id": remote["id"]})
                return resp
        return {"code": -1, "message": "远端不存在此旅客，无需删除"}

    def delete_vehicle(self, account: FerryAccount, db: Session, plate_number: str) -> dict:
        """从远端购票账号的常用车辆列表中删除指定车辆（按车牌匹配）"""
        remote_list = self._fetch_remote_vehicles(account, db)
        for remote in remote_list:
            if remote.get("plateNum") == plate_number:
                resp = self._authed_post("/user/vehicle/delete", account, db,
                                         data={"id": remote["id"]})
                return resp
        return {"code": -1, "message": "远端不存在此车辆，无需删除"}

    # ── 购票（HAR 逆向五步下单流程） ──────────────────────

    def book_ticket(
        self,
        account: FerryAccount,
        db: Session,
        trip: dict,
        passenger_ids: list,
        vehicle_id,
        preferred_seats: list = None,
        log_fn=None,
    ) -> dict:
        def log(msg, level="INFO"):
            if log_fn:
                log_fn(level, msg)

        preferred_seats = preferred_seats or []
        _, user_id = self._load_session(account)

        # Step 1: 持票预通知
        log("发送持票预通知...")
        try:
            resp = self._authed_post("/user/passenger/holding/notice", account, db, data={})
            print(f"预通知响应: {resp}")
        except Exception as e:
            log(f"预通知异常（忽略）：{e}", "WARN")

        from src.models import Passenger, Vehicle
        passengers = db.query(Passenger).filter(Passenger.id.in_(passenger_ids)).all()
        if not passengers:
            return {"success": False, "order_id": None, "message": "无有效旅客"}

        acc_id_str = str(account.id)

        # 选舱位
        # 旅客舱位（普通随车乘客用）
        chosen_seat = _pick_seat(trip.get("seatClasses") or [], preferred_seats)
        if not chosen_seat:
            return {"success": False, "order_id": None, "message": "没有可用舱位信息"}

        # 车辆及驾驶员信息（小客车票）
        plate_number = None
        car_seat = None
        driver_passenger_id = trip.get("_driver_passenger_id")  # 由 scheduler 注入到 trip dict

        if vehicle_id:
            v = db.query(Vehicle).get(vehicle_id)
            if v:
                plate_number = v.plate_number
                # 车辆舱位：优先取 pubCurrentCount > 0 的项，否则取第一项
                car_seat_raw = trip.get("driverSeatClass") or []
                if isinstance(car_seat_raw, dict):
                    car_seat_raw = [car_seat_raw]
                available_car = [sc for sc in car_seat_raw if sc.get("pubCurrentCount", 0) > 0]
                car_seat = available_car[0] if available_car else (car_seat_raw[0] if car_seat_raw else None)

        if vehicle_id and car_seat is None:
            return {"success": False, "order_id": None, "message": "班次中未找到车辆舱位信息，无法下单"}

        # 构建旅客订单项
        # 小客车票：驾驶员用车辆舱位 + 车牌，passType="10"；其余随车人员用客座舱位 + 空车牌，passType=1
        order_items = []
        driver_assigned = False
        for p in passengers:
            remote_ids = json.loads(p.remote_ids_json or "{}")
            pass_id = remote_ids.get(acc_id_str)
            if not pass_id:
                return {
                    "success": False, "order_id": None,
                    "message": f"旅客「{p.name}」未同步到此 Ferry 账号，请先执行同步",
                }
            cred_type = _ID_TYPE_TO_CRED_ID.get(p.id_type, 1)

            # 判断这个人是否是驾驶员
            is_driver = (
                not driver_assigned and
                plate_number is not None and
                car_seat is not None and
                (driver_passenger_id == p.id or driver_passenger_id is None)
            )

            if is_driver:
                driver_assigned = True
                order_items.append({
                    "passName": p.name,
                    "plateNum": plate_number,
                    "credentialType": cred_type,
                    "passId": pass_id,
                    "seatClassName": car_seat.get("className", "7座以下"),
                    "seatClass": car_seat.get("classNum", 62),
                    "ticketFee": int(car_seat.get("totalPrice", 0)),
                    "realFee": int(car_seat.get("totalPrice", 0)),
                    "freeChildCount": 0,
                    "passType": "10",
                })
            else:
                item = {
                    "passName": p.name,
                    "credentialType": cred_type,
                    "passId": pass_id,
                    "seatClassName": chosen_seat["className"],
                    "seatClass": chosen_seat["classNum"],
                    "ticketFee": chosen_seat.get("totalPrice", 0),
                    "realFee": chosen_seat.get("totalPrice", 0),
                    "freeChildCount": 0,
                    "passType": 1,
                }
                # 车辆票随车人员需要 plateNum 空字符串；纯旅客票不传该字段
                if plate_number is not None:
                    item["plateNum"] = ""
                order_items.append(item)

        if plate_number and not driver_assigned:
            return {
                "success": False, "order_id": None,
                "message": "车辆票必须指定至少一位驾驶员",
            }

        total_fee = sum(item["ticketFee"] for item in order_items)

        # Step 2: 提交持票订单
        log("提交持票订单...")
        # 纯旅客订单强制 buyTicketType=1；车辆票使用 trip 中的值（通常为 2）
        buy_ticket_type = trip.get("buyTicketType", 1) if vehicle_id else 1
        body = {
            "accountTypeId": "0",
            "userId": user_id,
            "buyTicketType": buy_ticket_type,
            "contactNum": account.phone,
            "lineNum": trip.get("lineNum"),
            "lineName": trip.get("lineName", ""),
            "lineNo": trip.get("lineNo"),
            "shipName": trip.get("shipName", ""),
            "startPortNo": trip.get("startPortNo"),
            "startPortName": trip.get("startPortName", ""),
            "endPortNo": trip.get("endPortNo"),
            "endPortName": trip.get("endPortName", ""),
            "sailDate": (trip.get("sailDate") or "").replace("/", "-"),
            "sailTime": trip.get("sailTime"),
            "lineDirect": 1,
            "totalFee": int(total_fee),
            "totalPayFee": int(total_fee),
            "sx": 0,
            "orderItemRequests": order_items,
            "busStartTime": "",
            "clxm": trip.get("clxm", ""),
            "clxh": trip.get("clxh", 0),
            "hxlxh": trip.get("hxlxh", 0),
            "hxlxm": trip.get("hxlxm", ""),
            "bus": 0,
            "bus2": 0,
            "dwh": trip.get("dwh"),
        }
        save_resp = self._authed_post(
            "/holding/save", account, db, data=body,
            extra_headers={"verifyCode": "undefined"},
        )
        if save_resp.get("code") != 200:
            return {
                "success": False, "order_id": None,
                "message": f"锁座失败：{save_resp.get('message', '')}",
            }

        raw_data = save_resp.get("data") or {}
        if isinstance(raw_data, dict):
            order_id = str(raw_data.get("orderId") or "")
        else:
            order_id = str(raw_data)
        if not order_id:
            return {"success": False, "order_id": None, "message": "锁座响应中无 orderId"}
        log(f"锁座成功，订单号: {order_id}")

        # Step 3: 轮询锁座确认
        log("等待锁座确认...")
        confirmed = False
        holding_fail_msg = ""
        for _ in range(12):
            try:
                res_resp = self._authed_post(
                    "/query/holding/res", account, db, data={"orderId": order_id}
                )
                code = res_resp.get("code")
                if code == 200:
                    confirmed = True
                    break
                # 收到明确的失败响应（如 code=300 余票不足），立即中断，无需继续轮询
                if code is not None and code != 200:
                    holding_fail_msg = res_resp.get("message") or f"code={code}"
                    log(f"锁座确认失败：{holding_fail_msg}", "WARN")
                    break
            except Exception:
                pass
            _time.sleep(1)

        if not confirmed:
            msg = f"锁座确认失败：{holding_fail_msg}" if holding_fail_msg else "锁座确认超时，请手动检查订单状态"
            return {
                "success": False, "order_id": order_id,
                "message": msg,
            }

        # Step 4: 获取支付截止时间
        expire_time = ""
        try:
            expire_resp = self._authed_get(
                "/user/order/expireTime", account, db, params={"orderId": order_id}
            )
            expire_time = expire_resp.get("data", "")
            if expire_time:
                log(f"请在 {expire_time} 前完成支付（订单号: {order_id}）")
        except Exception:
            pass

        return {
            "success": True,
            "order_id": order_id,
            "sail_time": trip.get("sailTime", ""),
            "ship_name": trip.get("shipName", ""),
            "payment_expire_at": expire_time,
            "message": "锁座成功，请尽快完成支付",
        }


# ── 辅助函数 ─────────────────────────────────────────────


def _save_remote_id(obj, account_id: int, remote_id: int, db):
    """将 ferry 系统的 remote_id 按 account_id 存入 obj.remote_ids_json"""
    try:
        rids = json.loads(obj.remote_ids_json or "{}")
        if str(account_id) not in rids:
            rids[str(account_id)] = remote_id
            obj.remote_ids_json = json.dumps(rids)
            db.commit()
    except Exception:
        pass


def _pick_seat(seat_classes: list, preferred: list):
    """从舱位列表中按偏好选取第一个有票舱位；无偏好则返回任意可用舱位"""
    available = [
        sc for sc in seat_classes
        if sc.get("pubCurrentCount", 0) > 0
    ]
    if preferred:
        for sc in available:
            if sc.get("className") in preferred:
                return sc
        return None  # 指定了偏好舱位但均无余票
    return available[0] if available else None


# ── 数据库写入辅助（与 sync_profile.py 的去重逻辑相同） ─────────────────

# 证件类型 ID → 名称映射（来自 /user/passenger/credential/type 接口）
_CRED_TYPE_MAP = {
    1: "身份证",
    4: "其他证件",
    5: "护照",
    6: "港澳居民来往内地通行证",
    7: "台湾居民来往大陆通行证",
    11: "新版外国人永久居留身份证",
}

# 名称 → ID 反向映射（本地推送到远端时使用）
_ID_TYPE_TO_CRED_ID = {v: k for k, v in _CRED_TYPE_MAP.items()}
# 兼容旧数据中的简写名称
_ID_TYPE_TO_CRED_ID.update({
    "港澳通行证": 6,
    "台湾通行证": 7,
    "其他":       4,
})


def _upsert_passenger(db: Session, data: dict, result: dict, account_id: int = None):
    id_number = (data.get("credentialNum") or "").strip()
    if not id_number:
        return
    existing = db.query(Passenger).filter_by(id_number=id_number).first()
    if existing:
        if account_id and data.get("id"):
            _save_remote_id(existing, account_id, data["id"], db)
        result["passengers_skipped"] += 1
        return
    cred_type_id = data.get("credentialTypeId", 1)
    rids = json.dumps({str(account_id): data["id"]}) if account_id and data.get("id") else "{}"
    db.add(Passenger(
        name=data.get("passName", ""),
        id_type=_CRED_TYPE_MAP.get(cred_type_id, "身份证"),
        id_number=id_number,
        phone=data.get("phoneNum") or None,
        remote_ids_json=rids,
        remark="自动同步(API)",
    ))
    db.commit()
    result["passengers_added"] += 1


def _upsert_vehicle(db: Session, data: dict, result: dict, account_id: int = None):
    plate = (data.get("plateNum") or "").strip()
    if not plate:
        return
    existing = db.query(Vehicle).filter_by(plate_number=plate).first()
    if existing:
        if account_id and data.get("id"):
            _save_remote_id(existing, account_id, data["id"], db)
        result["vehicles_skipped"] += 1
        return
    rids = json.dumps({str(account_id): data["id"]}) if account_id and data.get("id") else "{}"
    db.add(Vehicle(
        plate_number=plate,
        vehicle_type="",
        owner_name="",
        remote_ids_json=rids,
        remark="自动同步(API)",
    ))
    db.commit()
    result["vehicles_added"] += 1
