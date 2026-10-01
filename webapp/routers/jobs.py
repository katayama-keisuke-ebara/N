"""STEP アップロード・ジョブ実行・結果取得・ダウンロード API。"""

from __future__ import annotations

import io
import json
import urllib.parse
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse

from src.export.nesting_render import render_nesting_png
from webapp import db, storage
from webapp.deps import CurrentUser, get_current_user, verify_csrf
from webapp.schemas import CreateJobRequest, JobStatusResponse

router = APIRouter(prefix="/api", tags=["pipeline"])


def _content_disposition(filename: str) -> str:
    """HTTP ヘッダーは latin-1 のみ許容するため、非 ASCII ファイル名は RFC 5987 形式で付与する。"""
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii") or "download"
    quoted = urllib.parse.quote(filename)
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quoted}'


@router.post("/uploads", dependencies=[Depends(verify_csrf)])
async def upload_parts(files: list[UploadFile], user: CurrentUser = Depends(get_current_user)) -> dict:
    uploaded = []
    for f in files:
        content = await f.read()
        try:
            storage.validate_step_upload(f.filename or "", content)
        except storage.UploadValidationError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        upload_id, stored_path = storage.save_upload(user.id, f.filename or "part.step", content)
        db.create_upload(upload_id, user.id, f.filename or "part.step", str(stored_path))
        uploaded.append({"upload_id": upload_id, "orig_filename": f.filename})
    return {"uploads": uploaded}


@router.post("/jobs", dependencies=[Depends(verify_csrf)])
def create_job(
    body: CreateJobRequest, request: Request, user: CurrentUser = Depends(get_current_user),
) -> dict:
    if not body.parts and not body.manual_parts:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "部品が指定されていません (STEP または手動形状)")

    resolved_parts = []
    for part in body.parts:
        row = db.get_upload(part.upload_id, user.id)
        if row is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"不明なアップロードです: {part.upload_id}")
        resolved_parts.append({
            "stored_path": row["stored_path"],
            "orig_filename": row["orig_filename"],
            "quantity": part.quantity,
        })

    job_id = uuid.uuid4().hex
    params = body.model_dump()
    db.create_job(job_id, user.id, params)

    output_dir = storage.job_output_dir(user.id, job_id)
    request.app.state.job_manager.submit(
        job_id, user.id, [part.upload_id for part in body.parts],
        resolved_parts, [part.model_dump() for part in body.manual_parts],
        body.sheet_w, body.sheet_h, body.thickness, body.clearance, body.density, str(output_dir),
    )
    return {"job_id": job_id}


def _get_owned_job(job_id: str, user_id: int):
    row = db.get_job(job_id)
    if row is None or row["user_id"] != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ジョブが見つかりません")
    return row


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, user: CurrentUser = Depends(get_current_user)) -> JobStatusResponse:
    row = _get_owned_job(job_id, user.id)
    return JobStatusResponse(
        job_id=job_id, status=row["status"], progress=row["progress"], error=row["error"],
    )


@router.get("/jobs/{job_id}/candidates")
def get_job_candidates(job_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    row = _get_owned_job(job_id, user.id)
    if row["status"] != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, f"ジョブは完了していません (status={row['status']})")
    return {
        "results": json.loads(row["results_json"]),
        "candidates": json.loads(row["candidates_json"]),
    }


@router.get("/jobs/{job_id}/render")
def render_job(
    job_id: str, candidate: int = 0, user: CurrentUser = Depends(get_current_user),
) -> Response:
    row = _get_owned_job(job_id, user.id)
    if row["status"] != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "ジョブは完了していません")
    results = json.loads(row["results_json"])
    candidates = json.loads(row["candidates_json"])
    if not (0 <= candidate < len(candidates)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不正な候補番号です")
    params = json.loads(row["params_json"])
    png_bytes = render_nesting_png(results, candidates[candidate], params["sheet_w"], params["sheet_h"])
    return Response(content=png_bytes, media_type="image/png")


@router.get("/jobs/{job_id}/download/dxf")
def download_dxf(
    job_id: str, part: int = 0, user: CurrentUser = Depends(get_current_user),
) -> StreamingResponse:
    row = _get_owned_job(job_id, user.id)
    if row["status"] != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "ジョブは完了していません")
    results = json.loads(row["results_json"])
    if not (0 <= part < len(results)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不正な部品番号です")
    raw_dxf_path = results[part].get("dxf_path")
    if not raw_dxf_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "手動形状の単品 DXF はありません")
    dxf_path = Path(raw_dxf_path)
    if not dxf_path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DXF ファイルが見つかりません")
    data = dxf_path.read_bytes()
    filename = f"{Path(results[part]['step_path']).stem}_flat.dxf"
    return StreamingResponse(
        io.BytesIO(data), media_type="application/dxf",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.get("/jobs/{job_id}/download/zip")
def download_zip(job_id: str, user: CurrentUser = Depends(get_current_user)) -> StreamingResponse:
    row = _get_owned_job(job_id, user.id)
    if row["status"] != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "ジョブは完了していません")
    output_dir = storage.job_output_dir(user.id, job_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in output_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(output_dir))
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="netsingtool_{job_id}.zip"'},
    )


@router.get("/jobs/{job_id}/download/summary")
def download_summary(job_id: str, user: CurrentUser = Depends(get_current_user)) -> StreamingResponse:
    row = _get_owned_job(job_id, user.id)
    if row["status"] != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "ジョブは完了していません")
    path = storage.job_output_dir(user.id, job_id) / "summary.xlsx"
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "summary.xlsx が見つかりません")
    return StreamingResponse(
        io.BytesIO(path.read_bytes()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _content_disposition("summary.xlsx")},
    )
