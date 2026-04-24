"""FastAPI 主入口"""
import asyncio
import json
import logging
from collections import defaultdict
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi import APIRouter

from src.database import init_db
from src.models import Order  # noqa: F401 – ensure Order table is created
from src.api import auth, users, passengers, accounts, tasks, ports, settings, vehicles, trips, orders
from src.scheduler import set_ws_broadcast
from src.crawler.driver import check_selenium_health
from src.auth import get_current_user

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="嵊泗渡轮抢票系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 注册 API 路由 ─────────────────────────────────────────
for router in [auth.router, users.router, passengers.router,
               accounts.router, tasks.router, ports.router, settings.router,
               vehicles.router, trips.router, orders.router]:
    app.include_router(router)


# ─── 健康检查 ──────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/selenium/health")
def selenium_health(_=Depends(get_current_user)):
    return check_selenium_health()


# ─── WebSocket 实时日志 ────────────────────────────────────
# task_id -> set of WebSocket connections
_ws_connections: dict[int, Set[WebSocket]] = defaultdict(set)

# 主事件循环引用（由 lifespan 在启动时捕获，供后台线程调用）
_main_loop: asyncio.AbstractEventLoop | None = None


async def _broadcast(task_id: int, level: str, message: str):
    """广播日志到所有订阅该 task 的 WebSocket 客户端"""
    conns = _ws_connections.get(task_id, set())
    if not conns:
        return
    payload = json.dumps({"level": level, "message": message,
                          "time": asyncio.get_event_loop().time()})
    dead = set()
    for ws in conns:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    _ws_connections[task_id] -= dead


def _sync_broadcast(task_id: int, level: str, message: str):
    """从同步线程调用的广播入口，使用启动时捕获的主事件循环"""
    try:
        loop = _main_loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(_broadcast(task_id, level, message), loop)
    except Exception:
        pass


set_ws_broadcast(_sync_broadcast)


@app.websocket("/ws/tasks/{task_id}/logs")
async def ws_task_logs(websocket: WebSocket, task_id: int):
    await websocket.accept()
    _ws_connections[task_id].add(websocket)
    try:
        while True:
            # 保持连接，客户端断开时抛出异常
            await asyncio.sleep(30)
            await websocket.send_text(json.dumps({"ping": True}))
    except WebSocketDisconnect:
        pass
    finally:
        _ws_connections[task_id].discard(websocket)


# ─── 静态文件 / 前端 ───────────────────────────────────────
import os
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
@app.get("/{full_path:path}", include_in_schema=False)
def serve_spa(full_path: str = ""):
    index = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {"message": "前端文件未找到，请将 index.html 放入 src/static/"}


# ─── 启动事件 ──────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    init_db()
    logger.info("数据库初始化完成")

    # 重启后恢复未完成的任务：running → pending，并重新注册调度
    from src.database import SessionLocal
    from src.models import Task
    from src.scheduler import start_task
    db = SessionLocal()
    try:
        stale = db.query(Task).filter(Task.status.in_(["running", "pending"])).all()
        for task in stale:
            task.status = "pending"
        db.commit()
        for task in stale:
            start_task(task.id)
            logger.info(f"恢复任务 Task#{task.id}（{task.departure_name}→{task.destination_name}）")
    except Exception as e:
        logger.warning(f"恢复任务失败: {e}")
    finally:
        db.close()

    logger.info("嵊泗渡轮抢票系统启动成功！访问 http://localhost:8000")
