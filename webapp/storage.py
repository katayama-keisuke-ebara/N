"""アップロード/出力ファイルのユーザー別ストレージ管理と STEP ファイル検証。"""

from __future__ import annotations

import uuid
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "webapp_data"
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "output"

_ALLOWED_EXTENSIONS = {".step", ".stp"}
_MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200MB
_STEP_MAGIC = b"ISO-10303-21"


class UploadValidationError(ValueError):
    """アップロードされたファイルが STEP ファイルとして不正なとき。"""


def user_upload_dir(user_id: int) -> Path:
    path = UPLOAD_DIR / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_output_dir(user_id: int) -> Path:
    path = OUTPUT_DIR / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_output_dir(user_id: int, job_id: str) -> Path:
    path = user_output_dir(user_id) / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate_step_upload(filename: str, content: bytes) -> None:
    """拡張子・サイズ・マジックバイトを検証する。クライアント指定パスは一切信用しない。"""
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise UploadValidationError(f"STEP ファイル (.step/.stp) のみアップロード可能です: {filename}")
    if len(content) == 0:
        raise UploadValidationError(f"空のファイルはアップロードできません: {filename}")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise UploadValidationError(f"ファイルサイズが上限 (200MB) を超えています: {filename}")
    header = content[:200].lstrip()
    if _STEP_MAGIC not in header:
        raise UploadValidationError(f"STEP ファイル形式として認識できません: {filename}")


def save_upload(user_id: int, orig_filename: str, content: bytes) -> tuple[str, Path]:
    """検証済みファイルを UUID ベースのファイル名でユーザー別ディレクトリに保存する。"""
    upload_id = uuid.uuid4().hex
    suffix = Path(orig_filename).suffix.lower()
    stored_path = user_upload_dir(user_id) / f"{upload_id}{suffix}"
    stored_path.write_bytes(content)
    return upload_id, stored_path
