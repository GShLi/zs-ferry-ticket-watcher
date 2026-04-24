"""数据库连接与表初始化"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "ferry.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """创建全部表，并初始化默认数据"""
    from src.models import SystemUser, Setting, Vehicle, Order  # noqa: F401 触发模型注册
    Base.metadata.create_all(bind=engine)
    _migrate()
    _seed_defaults()


def _migrate():
    """对已存在的数据库做轻量级字段迁移"""
    with engine.connect() as conn:
        # tasks 表：补充 seat_class 列（首次添加该字段时兼容旧数据库）
        for ddl in [
            "ALTER TABLE tasks ADD COLUMN seat_class VARCHAR(32) NOT NULL DEFAULT ''",
            "ALTER TABLE tasks ADD COLUMN vehicle_id INTEGER REFERENCES vehicles(id)",
            "ALTER TABLE tasks ADD COLUMN sail_time_from VARCHAR(8) NOT NULL DEFAULT ''",
            "ALTER TABLE tasks ADD COLUMN sail_time_to VARCHAR(8) NOT NULL DEFAULT ''",
            "ALTER TABLE passengers ADD COLUMN remote_ids_json TEXT DEFAULT '{}'",
            "ALTER TABLE vehicles ADD COLUMN remote_ids_json TEXT DEFAULT '{}'",
            "ALTER TABLE tasks ADD COLUMN driver_passenger_id INTEGER REFERENCES passengers(id)",
            "ALTER TABLE tasks ADD COLUMN parent_task_id INTEGER REFERENCES tasks(id)",
            "ALTER TABLE tasks ADD COLUMN linked_trip_json TEXT",
        ]:
            try:
                conn.execute(__import__("sqlalchemy").text(ddl))
                conn.commit()
            except Exception:
                pass  # 列已存在则忽略


def _seed_defaults():
    """首次运行时写入默认 admin 用户和系统配置"""
    from src.models import SystemUser, Setting
    from src.auth import hash_password

    db = SessionLocal()
    try:
        # 默认 admin 用户
        if not db.query(SystemUser).filter_by(username="admin").first():
            admin = SystemUser(
                username="admin",
                password_hash=hash_password("admin123"),
                role="admin",
                is_active=True,
            )
            db.add(admin)
            print("[INIT] 默认管理员账号已创建：admin / admin123，请登录后立即修改密码！")

        # 默认系统设置
        defaults = {
            "selenium_url": "http://192.168.1.117:14444/wd/hub",
            "bark_key": "",
            "bark_server": "https://api.day.app",
        }
        for key, value in defaults.items():
            if not db.query(Setting).filter_by(key=key).first():
                db.add(Setting(key=key, value=value))

        db.commit()
    finally:
        db.close()
