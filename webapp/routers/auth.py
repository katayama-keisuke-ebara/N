"""ログイン/ログアウト。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from webapp import db, security
from webapp.deps import CSRF_COOKIE, SESSION_COOKIE, CurrentUser, get_current_user
from webapp.schemas import LoginRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"username": user.username}


@router.post("/login")
def login(body: LoginRequest, response: Response) -> dict:
    if security.login_rate_limiter.is_locked(body.username):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "ログイン試行回数が上限に達しました。しばらくしてから再度お試しください",
        )
    row = db.get_user_by_username(body.username)
    if row is None or not security.verify_password(body.password, row["password_hash"]):
        security.login_rate_limiter.record_failure(body.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "ユーザー名またはパスワードが違います")

    security.login_rate_limiter.record_success(body.username)
    token = security.create_session_token(row["id"])
    response.set_cookie(
        SESSION_COOKIE, token, max_age=security.SESSION_MAX_AGE,
        httponly=True, samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE, security.generate_csrf_token(), max_age=security.SESSION_MAX_AGE,
        httponly=False, samesite="lax",
    )
    return {"username": row["username"]}


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)
    return {"ok": True}
