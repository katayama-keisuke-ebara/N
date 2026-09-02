"""パスワードハッシュ・セッション署名・簡易ログインレート制限。"""

from __future__ import annotations

import secrets
import time
from pathlib import Path

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_DATA_DIR = Path(__file__).resolve().parent.parent / "webapp_data"
_SECRET_KEY_PATH = _DATA_DIR / "secret.key"

SESSION_MAX_AGE = 8 * 60 * 60  # 8時間
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_LOCKOUT_SECONDS = 15 * 60
# bcrypt はパスワードを72バイトまでしか扱えないため事前に長さを検証する。
_MAX_PASSWORD_BYTES = 72


def _load_or_create_secret_key() -> str:
    """再起動後もセッションが無効にならないよう、鍵をファイルに永続化する。"""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _SECRET_KEY_PATH.exists():
        return _SECRET_KEY_PATH.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    _SECRET_KEY_PATH.write_text(key, encoding="utf-8")
    return key


_serializer = URLSafeTimedSerializer(_load_or_create_secret_key(), salt="netsingtool-session")


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        raise ValueError(f"パスワードは {_MAX_PASSWORD_BYTES} バイト以内にしてください")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def create_session_token(user_id: int) -> str:
    return _serializer.dumps({"user_id": user_id})


def verify_session_token(token: str) -> int | None:
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("user_id")


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


class LoginRateLimiter:
    """ユーザー名単位で失敗試行を数え、一定回数超過で一時ロックする簡易実装。"""

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}

    def is_locked(self, username: str) -> bool:
        now = time.time()
        attempts = [t for t in self._failures.get(username, []) if now - t < _LOGIN_LOCKOUT_SECONDS]
        self._failures[username] = attempts
        return len(attempts) >= _LOGIN_MAX_ATTEMPTS

    def record_failure(self, username: str) -> None:
        self._failures.setdefault(username, []).append(time.time())

    def record_success(self, username: str) -> None:
        self._failures.pop(username, None)


login_rate_limiter = LoginRateLimiter()
