from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from . import auth as _auth
from .config import get_config, load_config, save_auth
from .pipeline import run_incremental_scan
from .scheduler import start, stop
from .state import init_db
from .web.routes import _limiter, router

_version_file = Path(__file__).parent.parent / "VERSION"
_version = _version_file.read_text().strip() if _version_file.exists() else "dev"


class _SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "SAMEORIGIN"
        h["Referrer-Policy"] = "strict-origin-when-cross-origin"
        h["X-XSS-Protection"] = "1; mode=block"
        # unsafe-inline required — all JS/CSS is inline in index.html (no external CDN)
        h["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    init_db()
    _auth.bootstrap(cfg.auth, save_auth)
    start(cfg.scan.schedule, lambda: run_incremental_scan(get_config()))
    yield
    stop()


app = FastAPI(
    title="Xenotag",
    version=_version,
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
)

app.add_middleware(_SecurityHeaders)
app.state.limiter = _limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")

app.include_router(router)
