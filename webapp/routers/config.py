"""ユーザー別パラメータ設定の取得/保存 (config.json の Web 版代替)。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from webapp import db
from webapp.deps import CurrentUser, get_current_user, verify_csrf
from webapp.schemas import UserConfigRequest

router = APIRouter(prefix="/api/config", tags=["config"])

_DEFAULTS = {
    "parts": [],
    "sheet_w": 1000.0,
    "sheet_h": 2000.0,
    "thickness": 10.0,
    "clearance": 5.0,
}


@router.get("")
def load_config(user: CurrentUser = Depends(get_current_user)) -> dict:
    return db.get_user_config(user.id) or dict(_DEFAULTS)


@router.post("", dependencies=[Depends(verify_csrf)])
def save_config(body: UserConfigRequest, user: CurrentUser = Depends(get_current_user)) -> dict:
    db.save_user_config(user.id, body.model_dump())
    return {"ok": True}
