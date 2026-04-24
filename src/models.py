"""SQLAlchemy ORM 模型定义"""
import json
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, ForeignKey
)
from sqlalchemy.orm import relationship
from src.database import Base


class SystemUser(Base):
    __tablename__ = "system_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(16), nullable=False, default="user")  # admin / user
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("system_users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class FerryAccount(Base):
    __tablename__ = "ferry_accounts"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), unique=True, nullable=False)
    password_enc = Column(Text, nullable=False)       # Fernet 加密
    cookies_json = Column(Text, default="[]")         # JSON list
    local_storage_json = Column(Text, default="{}")   # JSON object
    session_expires_at = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    remark = Column(String(128), default="")
    created_at = Column(DateTime, default=datetime.now)

    tasks = relationship("Task", back_populates="account")


class Passenger(Base):
    __tablename__ = "passengers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False)
    id_type = Column(String(32), nullable=False, default="身份证")  # 身份证/护照/港澳通行证/台湾通行证
    id_number = Column(String(64), nullable=False)
    phone = Column(String(20), nullable=True)
    remark = Column(String(128), default="")
    remote_ids_json = Column(Text, default="{}")  # {"<ferry_account_id>": passId}
    created_at = Column(DateTime, default=datetime.now)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("ferry_accounts.id"), nullable=False)
    departure_num = Column(Integer, nullable=False)
    departure_name = Column(String(64), nullable=False)
    destination_num = Column(Integer, nullable=False)
    destination_name = Column(String(64), nullable=False)
    travel_date = Column(String(16), nullable=False)  # YYYY-MM-DD
    ticket_type = Column(String(32), nullable=False, default="旅客")  # 旅客 / 小客车及随车人员
    seat_class = Column(String(32), nullable=False, default="")     # 舱位偏好（逗号分隔），空字符串=不限
    sail_time_from = Column(String(8), default="")                  # 开航时间范围起（HH:MM），空=不限
    sail_time_to = Column(String(8), default="")                    # 开航时间范围止（HH:MM），空=不限
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=True)  # 小客车票时选填
    driver_passenger_id = Column(Integer, ForeignKey("passengers.id"), nullable=True)  # 小客车票驾驶员（从随车旅客中选）
    passenger_ids = Column(Text, default="[]")  # JSON list of passenger IDs
    trigger_type = Column(String(16), nullable=False, default="poll")  # poll / schedule
    trigger_value = Column(String(64), nullable=False)  # poll: 间隔秒数; schedule: ISO datetime
    status = Column(String(16), default="pending")  # pending/running/booked/failed/stopped/waiting
    parent_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)  # 关联主任务 ID（从任务专用）
    linked_trip_json = Column(Text, nullable=True)   # 主任务成功后注入的班次数据（从任务直接下单用）
    created_by = Column(Integer, ForeignKey("system_users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    account = relationship("FerryAccount", back_populates="tasks")
    logs = relationship("TaskLog", back_populates="task", cascade="all, delete-orphan")

    @property
    def passenger_ids_list(self):
        return json.loads(self.passenger_ids or "[]")


class TaskLog(Base):
    __tablename__ = "task_logs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    level = Column(String(8), default="INFO")  # INFO / WARN / ERROR
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    task = relationship("Task", back_populates="logs")


class PortsCache(Base):
    __tablename__ = "ports_cache"

    id = Column(Integer, primary_key=True, index=True)
    start_port_num = Column(Integer, nullable=False)
    start_port_name = Column(String(64), nullable=False)
    end_port_num = Column(Integer, nullable=False)
    end_port_name = Column(String(64), nullable=False)
    updated_at = Column(DateTime, default=datetime.now)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    plate_number = Column(String(32), nullable=False, unique=True)  # 去重键
    vehicle_type = Column(String(64), nullable=False, default="")   # 车型
    owner_name = Column(String(64), nullable=False, default="")     # 车主姓名
    remark = Column(String(128), default="")
    remote_ids_json = Column(Text, default="{}")  # {"<ferry_account_id>": passId}
    created_at = Column(DateTime, default=datetime.now)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, default="")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    account_id = Column(Integer, ForeignKey("ferry_accounts.id"), nullable=True)
    order_id = Column(String(64), nullable=False, index=True)   # Ferry 远端订单号
    departure_name = Column(String(64), nullable=False, default="")
    destination_name = Column(String(64), nullable=False, default="")
    travel_date = Column(String(16), nullable=False, default="")
    sail_time = Column(String(8), nullable=True)
    ship_name = Column(String(64), nullable=True)
    passengers_json = Column(Text, default="[]")               # list of passenger names
    payment_expire_at = Column(String(32), nullable=True)      # 支付截止时间（字符串）
    status = Column(String(24), default="pending_payment")     # pending_payment / paid / cancelled
    created_at = Column(DateTime, default=datetime.now)
