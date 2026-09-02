"""FastAPI 依存関係: セッション認証・CSRF検証。"""

from __future__ import annotations

from fastapi import Cookie, Header, HTTPException, Request, status

from webapp import db, security

SESSION_COOKIE = "session"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


class CurrentUser:
    def __init__(self, id: int, username: str) -> None:
        self.id = id
        self.username = username


def get_current_user(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> CurrentUser:
    if not session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ログインが必要です")
    user_id = security.verify_session_token(session)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "セッションが無効です。再ログインしてください")
    row = db.get_user_by_id(user_id)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ユーザーが存在しません")
    return CurrentUser(id=row["id"], username=row["username"])


def verify_csrf(
    request: Request,
    csrf_token: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    x_csrf_token: str | None = Header(default=None, alias=CSRF_HEADER),
) -> None:
    """Double-submit cookie 方式の CSRF 検証 (状態変更系リクエストに適用)。"""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if not csrf_token or not x_csrf_token or csrf_token != x_csrf_token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF トークンが不正です")
