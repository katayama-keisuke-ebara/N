"""FastAPI アプリケーションのエントリポイント。

起動: .venv\\Scripts\\python.exe -m webapp.main
(本番運用時は Windows Service 化した uvicorn からこのモジュールを指す)
"""

from __future__ import annotations

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
    return templates.TemplateResponse(request, "index.html")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("webapp.main:app", host="0.0.0.0", port=8000)
