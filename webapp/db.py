"""SQLite によるユーザー/ジョブ/設定の永続化 (社内少人数利用を想定した最小構成)。"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "webapp_data"
DB_PATH = DATA_DIR / "app.db"

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress TEXT NOT NULL DEFAULT '',
    error TEXT,
    params_json TEXT NOT NULL,
    results_json TEXT,
    candidates_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS user_config (
    user_id INTEGER PRIMARY KEY,
    config_json TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    orig_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


@contextmanager
def get_connection():
    with _lock:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


# ── users ────────────────────────────────────────────────────────────────

def create_user(username: str, password_hash: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_user_by_username(username: str) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


# ── jobs ─────────────────────────────────────────────────────────────────

def create_job(job_id: str, user_id: int, params: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO jobs (id, user_id, status, params_json) VALUES (?, ?, 'queued', ?)",
            (job_id, user_id, json.dumps(params, ensure_ascii=False)),
        )
        conn.commit()


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: str | None = None,
    error: str | None = None,
    results: list | None = None,
    candidates: list | None = None,
) -> None:
    fields = []
    values: list = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if progress is not None:
        fields.append("progress = ?")
        values.append(progress)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if results is not None:
        fields.append("results_json = ?")
        values.append(json.dumps(results, ensure_ascii=False))
    if candidates is not None:
        fields.append("candidates_json = ?")
        values.append(json.dumps(candidates, ensure_ascii=False))
    fields.append("updated_at = datetime('now')")
    values.append(job_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()


def get_job(job_id: str) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def list_jobs_for_retention() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, user_id, created_at FROM jobs "
            "WHERE status IN ('done', 'error') "
            "ORDER BY user_id, created_at DESC, id DESC"
        ).fetchall()


def list_active_job_params() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, params_json FROM jobs WHERE status IN ('queued', 'running')"
        ).fetchall()


def delete_job(job_id: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()


# ── user_config ──────────────────────────────────────────────────────────

def get_user_config(user_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT config_json FROM user_config WHERE user_id = ?", (user_id,)
        ).fetchone()
        return json.loads(row["config_json"]) if row else None


def save_user_config(user_id: int, config: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO user_config (user_id, config_json) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET config_json = excluded.config_json",
            (user_id, json.dumps(config, ensure_ascii=False)),
        )
        conn.commit()


# ── uploads ──────────────────────────────────────────────────────────────

def create_upload(upload_id: str, user_id: int, orig_filename: str, stored_path: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO uploads (id, user_id, orig_filename, stored_path) VALUES (?, ?, ?, ?)",
            (upload_id, user_id, orig_filename, stored_path),
        )
        conn.commit()


def get_upload(upload_id: str, user_id: int) -> sqlite3.Row | None:
    """所有者(user_id)が一致する場合のみアップロード情報を返す (IDOR対策)。"""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM uploads WHERE id = ? AND user_id = ?", (upload_id, user_id)
        ).fetchone()


def list_stale_uploads(cutoff_iso: str) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, user_id, stored_path FROM uploads WHERE created_at < ?",
            (cutoff_iso,),
        ).fetchall()


def delete_upload(upload_id: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
        conn.commit()
