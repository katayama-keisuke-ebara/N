"""FastAPI アプリケーションのエントリポイント。

起動: .venv\\Scripts\\python.exe -m webapp.main
(本番運用時は Windows Service 化した uvicorn からこのモジュールを指す)

IIS でリバースプロキシ配下 (例: https://xxx.com/nesting/ -> http://127.0.0.1:8090/、
パスのプレフィックスは剥がされてバックエンドに届く) に公開する場合は、環境変数
NESTING_ROOT_PATH に外部から見えるプレフィックス (例: "/nesting") を設定して起動する。
未設定時 (ローカル直アクセス) は従来通り空文字のまま動作する。

注意: この NESTING_ROOT_PATH は HTML の <base href> 生成にのみ使い、FastAPI(root_path=...)
には渡さない。ASGI scope の root_path は「実際のパスの先頭にそのプレフィックスが付いている」
ことを前提にした機構であり、IIS 側でプレフィックスを剥がして転送する本構成でこれを設定すると
StaticFiles のパス解決が壊れて静的ファイルが 404 になる。
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from webapp import db
from webapp.jobs import JobManager
from webapp.routers import auth, config, jobs

_BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))

ROOT_PATH = os.environ.get("NESTING_ROOT_PATH", "").rstrip("/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    app.state.job_manager = JobManager()
    yield
    app.state.job_manager.shutdown()


app = FastAPI(title="NetsingTool Web", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(config.router)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"root_path": ROOT_PATH})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"root_path": ROOT_PATH})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("webapp.main:app", host="0.0.0.0", port=8000)
