"""ユーザー別パラメータ設定の取得/保存 (config.json の Web 版代替)。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from webapp import db
from webapp.deps import CurrentUser, get_current_user, verify_csrf
from webapp.schemas import PartsParamsPayload, UserConfigRequest
from webapp.services.params_io_service import MAX_FILE_BYTES, ParamsIOService, ParamsImportError

router = APIRouter(prefix="/api/config", tags=["config"])

_DEFAULTS = {
    "parts": [],
    "sheet_w": 1000.0,
    "sheet_h": 2000.0,
    "thickness": 10.0,
    "clearance": 5.0,
    "density": 1.0,
}


@router.get("")
def load_config(user: CurrentUser = Depends(get_current_user)) -> dict:
    # 保存済み設定に無いキー(旧データ由来の density 欠損等)はデフォルトで補完する。
    return {**_DEFAULTS, **(db.get_user_config(user.id) or {})}


@router.post("", dependencies=[Depends(verify_csrf)])
def save_config(body: UserConfigRequest, user: CurrentUser = Depends(get_current_user)) -> dict:
    db.save_user_config(user.id, body.model_dump())
    return {"ok": True}


@router.post("/export", dependencies=[Depends(verify_csrf)])
def export_params(body: PartsParamsPayload, user: CurrentUser = Depends(get_current_user)) -> Response:
    return Response(
        content=ParamsIOService().build_workbook(body.model_dump()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="netsingtool_params.xlsx"'},
    )


@router.post("/import", response_model=PartsParamsPayload, dependencies=[Depends(verify_csrf)])
async def import_params(file: UploadFile, user: CurrentUser = Depends(get_current_user)) -> dict:
    try:
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise ParamsImportError("Excel (.xlsx) ファイルを選択してください")
        content = await file.read(MAX_FILE_BYTES + 1)
        return ParamsIOService().parse_workbook(content)
    except ParamsImportError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        await file.close()
