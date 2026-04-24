from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from src.database import get_db, SessionLocal
from src.models import FerryAccount, SystemUser
from src.auth import get_current_user
from src.schemas import FerryAccountCreate, FerryAccountUpdate, FerryAccountOut, SyncResult
from src.crawler.session import encrypt_password, decrypt_password

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("/", response_model=list[FerryAccountOut])
def list_accounts(
    db: Session = Depends(get_db),
    _: SystemUser = Depends(get_current_user),
):
    return [FerryAccountOut.model_validate(a) for a in db.query(FerryAccount).all()]


@router.post("/", response_model=FerryAccountOut, status_code=201)
def create_account(
    body: FerryAccountCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: SystemUser = Depends(get_current_user),
):
    if db.query(FerryAccount).filter_by(phone=body.phone).first():
        raise HTTPException(status_code=400, detail="该手机号已存在")
    acc = FerryAccount(
        phone=body.phone,
        password_enc=encrypt_password(body.password),
        remark=body.remark,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    # 添加账号后在后台自动同步联系人和车辆
    background_tasks.add_task(_bg_sync, acc.id)
    return FerryAccountOut.model_validate(acc)


@router.put("/{acc_id}", response_model=FerryAccountOut)
def update_account(
    acc_id: int,
    body: FerryAccountUpdate,
    db: Session = Depends(get_db),
    _: SystemUser = Depends(get_current_user),
):
    acc = db.query(FerryAccount).get(acc_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    if body.password:
        acc.password_enc = encrypt_password(body.password)
        # 密码变更时清除已保存会话，强制重新登录
        acc.cookies_json = "[]"
        acc.local_storage_json = "{}"
        acc.session_expires_at = None
    if body.remark is not None:
        acc.remark = body.remark
    db.commit()
    db.refresh(acc)
    return FerryAccountOut.model_validate(acc)


@router.delete("/{acc_id}", status_code=204)
def delete_account(
    acc_id: int,
    db: Session = Depends(get_db),
    _: SystemUser = Depends(get_current_user),
):
    acc = db.query(FerryAccount).get(acc_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    db.delete(acc)
    db.commit()


@router.post("/{acc_id}/test-login")
def test_login(
    acc_id: int,
    db: Session = Depends(get_db),
    _: SystemUser = Depends(get_current_user),
):
    """测试该账号登录状态，若会话有效则复用，否则重新登录"""
    from src.crawler.factory import get_backend
    acc = db.query(FerryAccount).get(acc_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    try:
        backend = get_backend(db)
        message = backend.login(acc, db)
        return {"success": True, "message": message}
    except Exception as e:
        print(e)
        return {"success": False, "message": str(e)}


@router.post("/{acc_id}/sync", response_model=SyncResult)
def sync_account(
    acc_id: int,
    db: Session = Depends(get_db),
    _: SystemUser = Depends(get_current_user),
):
    """登录该 Ferry 账号，同步常用联系人和车辆到本地（去重）"""
    from src.crawler.factory import get_backend
    acc = db.query(FerryAccount).get(acc_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    try:
        backend = get_backend(db)
        return backend.sync_profile(acc, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{acc_id}/import-cookies")
def import_cookies(
    acc_id: int,
    body: dict,
    db: Session = Depends(get_db),
    _: SystemUser = Depends(get_current_user),
):
    """接收浏览器 DevTools 粘贴的 Cookie 字符串（name=value; name2=value2），
    解析后存入 cookies_json，使后续 API 请求携带 acw_tc 等 WAF Cookie。"""
    import json
    acc = db.query(FerryAccount).get(acc_id)
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")
    raw = (body.get("cookies") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Cookie 字符串不能为空")
    # 解析 "name=value; name2=value2" 格式
    cookies_list = []
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            name = name.strip()
            value = value.strip()
            if name:
                cookies_list.append({
                    "name": name, "value": value,
                    "domain": "pc.ssky123.com", "path": "/"
                })
    if not cookies_list:
        raise HTTPException(status_code=400, detail="未能解析出任何 Cookie")
    acc.cookies_json = json.dumps(cookies_list, ensure_ascii=False)
    db.commit()
    return {"success": True, "message": f"已导入 {len(cookies_list)} 个 Cookie"}


def _bg_sync(acc_id: int):
    """在后台线程中为新添加账号执行同步（添加账号时自动触发）"""
    from src.crawler.factory import get_backend
    db = SessionLocal()
    try:
        acc = db.query(FerryAccount).get(acc_id)
        if not acc:
            return
        backend = get_backend(db)
        result = backend.sync_profile(acc, db)
        print(
            f"[SYNC] 账号 {acc.phone} 同步完成："
            f"联系人 +{result['passengers_added']} 跳过{result['passengers_skipped']}，"
            f"车辆 +{result['vehicles_added']} 跳过{result['vehicles_skipped']}"
        )
        if result["errors"]:
            print(f"[SYNC] 同步错误: {result['errors']}")
    except Exception as e:
        print(f"[SYNC] 账号 {acc_id} 后台同步异常: {e}")
    finally:
        db.close()
