"""webapp_data のジョブ成果物とアップロードを保持ポリシーに従って削除する。"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from webapp import db, storage

logger = logging.getLogger(__name__)

KEEP_JOBS_PER_USER = int(os.environ.get("NESTING_RETENTION_KEEP_JOBS", "20"))
MAX_JOB_AGE_DAYS = int(os.environ.get("NESTING_RETENTION_MAX_AGE_DAYS", "30"))
ORPHAN_UPLOAD_MAX_AGE_HOURS = int(
    os.environ.get("NESTING_RETENTION_UPLOAD_MAX_AGE_HOURS", "24")
)
CLEANUP_INTERVAL_SECONDS = int(
    os.environ.get("NESTING_RETENTION_INTERVAL_SECONDS", "3600")
)

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
KEEP_LOG_FILES = int(os.environ.get("NESTING_RETENTION_KEEP_LOG_FILES", "20"))
MAX_LOG_AGE_DAYS = int(os.environ.get("NESTING_RETENTION_LOG_MAX_AGE_DAYS", "30"))
_LOG_CLEANUP_GLOBS = (
    "server_*.log",
    "service_stdout.log.*",
    "service_stdout.log-*",
    "service_stderr.log.*",
    "service_stderr.log-*",
)


def _parse_db_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def cleanup_old_jobs(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_JOB_AGE_DAYS)
    jobs_by_user: dict[int, list] = defaultdict(list)
    for row in db.list_jobs_for_retention():
        jobs_by_user[int(row["user_id"])].append(row)

    deleted = 0
    for user_id, rows in jobs_by_user.items():
        for index, row in enumerate(rows):
            if index < KEEP_JOBS_PER_USER and _parse_db_datetime(row["created_at"]) >= cutoff:
                continue
            job_id = str(row["id"])
            try:
                storage.delete_job_output(user_id, job_id)
                db.delete_job(job_id)
                deleted += 1
                logger.info("期限切れジョブを削除しました (user=%s, job=%s)", user_id, job_id)
            except Exception:
                logger.warning(
                    "期限切れジョブの削除に失敗しました (user=%s, job=%s)",
                    user_id,
                    job_id,
                    exc_info=True,
                )
    return deleted


def _active_upload_ids() -> set[str] | None:
    active_ids: set[str] = set()
    for row in db.list_active_job_params():
        try:
            params = json.loads(row["params_json"])
            active_ids.update(
                part["upload_id"] for part in params.get("parts", []) if part.get("upload_id")
            )
        except (json.JSONDecodeError, TypeError, KeyError):
            logger.warning(
                "実行中ジョブのアップロード参照を解析できません (job=%s)",
                row["id"],
                exc_info=True,
            )
            return None
    return active_ids


def cleanup_orphaned_uploads(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=ORPHAN_UPLOAD_MAX_AGE_HOURS)
    active_ids = _active_upload_ids()
    if active_ids is None:
        return 0

    deleted = 0
    cutoff_iso = cutoff.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for row in db.list_stale_uploads(cutoff_iso):
        upload_id = str(row["id"])
        if upload_id in active_ids:
            continue
        try:
            storage.delete_upload_file(row["stored_path"])
            db.delete_upload(upload_id)
            deleted += 1
            logger.info(
                "未使用アップロードを削除しました (user=%s, upload=%s)",
                row["user_id"],
                upload_id,
            )
        except Exception:
            logger.warning(
                "未使用アップロードの削除に失敗しました (user=%s, upload=%s)",
                row["user_id"],
                upload_id,
                exc_info=True,
            )
    return deleted


def cleanup_old_logs(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_LOG_AGE_DAYS)
    candidates: list[tuple[Path, float]] = []
    seen: set[Path] = set()
    for pattern in _LOG_CLEANUP_GLOBS:
        for path in LOG_DIR.glob(pattern):
            if path in seen:
                continue
            seen.add(path)
            try:
                if path.is_file():
                    candidates.append((path, path.stat().st_mtime))
            except OSError:
                logger.warning("ログ情報の取得に失敗しました (path=%s)", path, exc_info=True)
    candidates.sort(key=lambda item: item[1], reverse=True)

    deleted = 0
    for index, (path, modified_timestamp) in enumerate(candidates):
        modified_at = datetime.fromtimestamp(modified_timestamp, tz=timezone.utc)
        if index < KEEP_LOG_FILES and modified_at >= cutoff:
            continue
        try:
            path.unlink()
            deleted += 1
            logger.info("期限切れログを削除しました (path=%s)", path)
        except OSError:
            logger.warning("期限切れログの削除に失敗しました (path=%s)", path, exc_info=True)
    return deleted


def run_cleanup_once() -> None:
    deleted_jobs = cleanup_old_jobs()
    deleted_uploads = cleanup_orphaned_uploads()
    deleted_logs = cleanup_old_logs()
    logger.info(
        "定期クリーンアップ完了 (jobs=%s, uploads=%s, logs=%s)",
        deleted_jobs,
        deleted_uploads,
        deleted_logs,
    )


class RetentionScheduler:
    def __init__(self, interval_seconds: int = CLEANUP_INTERVAL_SECONDS) -> None:
        self._interval_seconds = max(1, interval_seconds)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                run_cleanup_once()
            except Exception:
                logger.error("webapp_data クリーンアップに失敗しました", exc_info=True)
            self._stop_event.wait(self._interval_seconds)

    def shutdown(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5)