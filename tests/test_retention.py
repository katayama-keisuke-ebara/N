from __future__ import annotations

import json
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from webapp import db, retention, storage
from webapp.jobs import JobManager


@pytest.fixture
def isolated_webapp_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data_dir = tmp_path / "webapp_data"
    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "DB_PATH", data_dir / "app.db")
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(storage, "OUTPUT_DIR", data_dir / "output")
    monkeypatch.setattr(retention, "KEEP_JOBS_PER_USER", 20)
    monkeypatch.setattr(retention, "MAX_JOB_AGE_DAYS", 30)
    monkeypatch.setattr(retention, "ORPHAN_UPLOAD_MAX_AGE_HOURS", 24)
    db.init_db()
    return data_dir


def _create_user(username: str) -> int:
    return db.create_user(username, "hash")


def _create_job(
    job_id: str,
    user_id: int,
    status: str,
    created_at: datetime,
    upload_ids: list[str] | None = None,
) -> None:
    params = {"parts": [{"upload_id": value} for value in upload_ids or []]}
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO jobs (id, user_id, status, params_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                job_id,
                user_id,
                status,
                json.dumps(params),
                created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()


def _create_upload(
    data_dir: Path,
    upload_id: str,
    user_id: int,
    created_at: datetime,
) -> Path:
    path = data_dir / "uploads" / str(user_id) / f"{upload_id}.step"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"STEP")
    db.create_upload(upload_id, user_id, f"{upload_id}.step", str(path))
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE uploads SET created_at = ? WHERE id = ?",
            (
                created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                upload_id,
            ),
        )
        conn.commit()
    return path


def test_cleanup_old_jobs_applies_count_and_age_per_user(
    isolated_webapp_data: Path,
) -> None:
    now = datetime(2026, 3, 1, tzinfo=timezone.utc)
    first_user = _create_user("first")
    second_user = _create_user("second")

    for index in range(22):
        job_id = f"recent-{index:02d}"
        _create_job(job_id, first_user, "done", now - timedelta(hours=index))
        output = storage.job_output_dir(first_user, job_id)
        (output / "result.txt").write_text("result", encoding="ascii")

    _create_job("old-done", first_user, "error", now - timedelta(days=31))
    storage.job_output_dir(first_user, "old-done")
    _create_job("old-running", first_user, "running", now - timedelta(days=60))
    storage.job_output_dir(first_user, "old-running")
    _create_job("other-user", second_user, "done", now - timedelta(days=1))
    storage.job_output_dir(second_user, "other-user")

    assert retention.cleanup_old_jobs(now) == 3

    assert db.get_job("recent-19") is not None
    assert db.get_job("recent-20") is None
    assert db.get_job("recent-21") is None
    assert db.get_job("old-done") is None
    assert db.get_job("old-running") is not None
    assert db.get_job("other-user") is not None
    assert not (isolated_webapp_data / "output" / str(first_user) / "recent-20").exists()
    assert (isolated_webapp_data / "output" / str(first_user) / "old-running").exists()


def test_cleanup_orphaned_uploads_preserves_active_and_fresh_uploads(
    isolated_webapp_data: Path,
) -> None:
    now = datetime(2026, 3, 1, tzinfo=timezone.utc)
    user_id = _create_user("owner")
    stale_path = _create_upload(
        isolated_webapp_data, "stale", user_id, now - timedelta(hours=25)
    )
    active_path = _create_upload(
        isolated_webapp_data, "active", user_id, now - timedelta(hours=25)
    )
    fresh_path = _create_upload(
        isolated_webapp_data, "fresh", user_id, now - timedelta(hours=23)
    )
    _create_job("running", user_id, "running", now, ["active"])

    assert retention.cleanup_orphaned_uploads(now) == 1

    assert not stale_path.exists()
    assert db.get_upload("stale", user_id) is None
    assert active_path.exists()
    assert db.get_upload("active", user_id) is not None
    assert fresh_path.exists()
    assert db.get_upload("fresh", user_id) is not None


@pytest.mark.parametrize("failed", [False, True])
def test_job_completion_removes_consumed_upload(
    isolated_webapp_data: Path,
    failed: bool,
) -> None:
    now = datetime(2026, 3, 1, tzinfo=timezone.utc)
    user_id = _create_user(f"owner-{failed}")
    upload_id = f"upload-{failed}"
    upload_path = _create_upload(isolated_webapp_data, upload_id, user_id, now)
    job_id = f"job-{failed}"
    _create_job(job_id, user_id, "running", now, [upload_id])
    future: Future = Future()
    if failed:
        future.set_exception(RuntimeError("processing failed"))
    else:
        future.set_result({"results": [], "candidates": []})

    manager = object.__new__(JobManager)
    manager._on_done(job_id, user_id, [upload_id], future)

    assert not upload_path.exists()
    assert db.get_upload(upload_id, user_id) is None
    expected_status = "error" if failed else "done"
    assert db.get_job(job_id)["status"] == expected_status
