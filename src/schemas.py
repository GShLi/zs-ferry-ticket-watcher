"""Pydantic 请求/响应模型"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


# ─── 系统用户 ───────────────────────────────────────────
class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"


class UserUpdate(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── 认证 ────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ─── Ferry 账号 ──────────────────────────────────────────
class FerryAccountCreate(BaseModel):
    phone: str
    password: str
    remark: str = ""


class FerryAccountUpdate(BaseModel):
    password: Optional[str] = None
    remark: Optional[str] = None


class FerryAccountOut(BaseModel):
    id: int
    phone: str
    remark: str
    session_expires_at: Optional[datetime]
    last_login_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── 旅客 ────────────────────────────────────────────────
class PassengerCreate(BaseModel):
    name: str
    id_type: str = "身份证"
    id_number: str
    phone: Optional[str] = None
    remark: str = ""


class PassengerUpdate(BaseModel):
    name: Optional[str] = None
    id_type: Optional[str] = None
    id_number: Optional[str] = None
    phone: Optional[str] = None
    remark: Optional[str] = None


class PassengerOut(BaseModel):
    id: int
    name: str
    id_type: str
    id_number: str
    phone: Optional[str]
    remark: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── 港口/航线 ───────────────────────────────────────────
class PortRouteOut(BaseModel):
    start_port_num: int
    start_port_name: str
    end_port_num: int
    end_port_name: str


class PortsCacheOut(BaseModel):
    routes: List[PortRouteOut]
    updated_at: Optional[datetime]


# ─── 任务 ────────────────────────────────────────────────
class LinkedPassengerTask(BaseModel):
    """随主任务同步创建的关联旅客单（等待主任务成功后触发）"""
    passenger_ids: List[int]
    seat_classes: List[str] = []


class TaskCreate(BaseModel):
    account_id: int
    departure_num: int
    departure_name: str
    destination_num: int
    destination_name: str
    travel_date: str          # YYYY-MM-DD
    ticket_type: str = "旅客"
    seat_classes: List[str] = []        # 舱位偏好（多选），空列表=不限
    sail_time_from: str = ""            # 开航时间起（HH:MM），空=不限
    sail_time_to: str = ""              # 开航时间止（HH:MM），空=不限
    vehicle_id: Optional[int] = None          # 小客车票时选填
    driver_passenger_id: Optional[int] = None  # 小客车票驾驶员（来自旅客列表）
    passenger_ids: List[int] = []
    trigger_type: str = "poll"          # poll / schedule
    trigger_value: str = ""             # poll: ""（随机间隔）; schedule: ISO datetime
    linked_passenger_task: Optional["LinkedPassengerTask"] = None  # 创建时附带的关联旅客单


class TaskUpdate(BaseModel):
    """编辑任务（不可更改出发/到达港口；不可新增/删除关联旅客单）"""
    account_id: Optional[int] = None
    travel_date: Optional[str] = None
    ticket_type: Optional[str] = None
    seat_classes: Optional[List[str]] = None
    sail_time_from: Optional[str] = None
    sail_time_to: Optional[str] = None
    vehicle_id: Optional[int] = None
    driver_passenger_id: Optional[int] = None
    passenger_ids: Optional[List[int]] = None
    trigger_type: Optional[str] = None
    trigger_value: Optional[str] = None


class TaskOut(BaseModel):
    id: int
    account_id: int
    departure_num: int
    departure_name: str
    destination_num: int
    destination_name: str
    travel_date: str
    ticket_type: str
    seat_classes: List[str]
    sail_time_from: str
    sail_time_to: str
    vehicle_id: Optional[int]
    driver_passenger_id: Optional[int]
    passenger_ids: List[int]
    trigger_type: str
    trigger_value: str
    status: str
    parent_task_id: Optional[int] = None
    child_task_ids: List[int] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def model_validate(cls, obj, **kwargs):
        import json
        if hasattr(obj, "passenger_ids") and isinstance(obj.passenger_ids, str):
            obj.passenger_ids = json.loads(obj.passenger_ids or "[]")
        return super().model_validate(obj, **kwargs)


# ─── 任务日志 ────────────────────────────────────────────
class TaskLogOut(BaseModel):
    id: int
    task_id: int
    level: str
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── 车辆 ────────────────────────────────────────────────
class VehicleCreate(BaseModel):
    plate_number: str
    vehicle_type: str = ""
    owner_name: str = ""
    remark: str = ""


class VehicleUpdate(BaseModel):
    vehicle_type: Optional[str] = None
    owner_name: Optional[str] = None
    remark: Optional[str] = None


class VehicleOut(BaseModel):
    id: int
    plate_number: str
    vehicle_type: str
    owner_name: str
    remark: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── 同步结果 ─────────────────────────────────────────────
class SyncResult(BaseModel):
    passengers_added: int = 0
    passengers_skipped: int = 0
    vehicles_added: int = 0
    vehicles_skipped: int = 0
    errors: List[str] = []


# ─── 系统设置 ────────────────────────────────────────────
class SettingItem(BaseModel):
    key: str
    value: str


class SettingsUpdate(BaseModel):
    selenium_url: Optional[str] = None
    bark_key: Optional[str] = None
    bark_server: Optional[str] = None
    crawler_backend: Optional[str] = None  # "api" | "selenium"
