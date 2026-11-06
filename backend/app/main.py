import logging
import os
from contextlib import asynccontextmanager

import truststore

# Use the Windows certificate store so HTTPS works behind antivirus/corporate TLS inspection.
truststore.inject_into_ssl()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import r as api_router
from .config import ROOT, get_settings
from .db import init_db
from .llm import LLMError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if os.environ.get("JOBPILOT_NO_WORKER") != "1":
        from .worker import start_scheduler, stop_scheduler
        start_scheduler()
        yield
        stop_scheduler()
    else:
        yield


app = FastAPI(title="JobPilot", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[get_settings().frontend_origin], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router)


@app.exception_handler(LLMError)
async def llm_error(_: Request, e: LLMError):
    return JSONResponse(status_code=503, content={"detail": str(e)})


DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
