import logging
import os
from contextlib import asynccontextmanager

import truststore

# Use the Windows certificate store so HTTPS works behind antivirus/corporate TLS inspection.
truststore.inject_into_ssl()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from . import auth  # noqa: E402
from .api import r as api_router  # noqa: E402
from .config import ROOT, get_settings  # noqa: E402
from .db import init_db  # noqa: E402
from .llm import LLMError  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings().validate_hosted()  # refuses to start a hosted instance without a password
    init_db()
    if os.environ.get("JOBPILOT_NO_WORKER") != "1":
        from .worker import start_scheduler, stop_scheduler
        start_scheduler()
        yield
        stop_scheduler()
    else:
        yield


app = FastAPI(title="JobPilot", version="1.0", lifespan=lifespan,
              docs_url=None if get_settings().hosted else "/docs",
              redoc_url=None, openapi_url=None if get_settings().hosted else "/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=[get_settings().frontend_origin], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def owner_guard(request: Request, call_next):
    """Hosted mode: every /api route except login/status requires a valid session cookie, and
    state-changing requests must come from an allowed origin."""
    path = request.url.path
    if get_settings().hosted and path.startswith("/api/") and path not in auth.PUBLIC_PATHS:
        if not auth.is_authenticated(request):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
        if request.method not in auth.SAFE_METHODS and not auth.origin_ok(request):
            return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
    return await call_next(request)


app.include_router(auth.router)
app.include_router(api_router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


@app.exception_handler(LLMError)
async def llm_error(_: Request, e: LLMError):
    return JSONResponse(status_code=503, content={"detail": str(e)})


DIST = ROOT / "frontend" / "dist"
if DIST.exists() and not get_settings().hosted:
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
