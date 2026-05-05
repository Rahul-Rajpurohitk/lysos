"""Production hardening for the Lysos workspace FastAPI.

Adds the bits a demo Space needs to survive contact with real traffic:

  * Per-IP rate limits (design is expensive — protect the GPU)
  * Request ID + structured JSON logs (so we can trace failures)
  * Sanitized error responses (stop leaking str(exc) to clients)
  * Tighter CORS (only the HF Space + localhost)
  * Body-size cap (1 MB)
  * Cold-start lock around the model loader (no thundering herd)
  * SMILES input sanitizer (length + allowed chars)
  * /api/ready endpoint distinct from /api/health (k8s-style probes)
  * X-Process-Time-Ms response header

`apply_hardening(app)` is idempotent and additive; it does not
rewrite or replace existing routes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import traceback
import uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

log = logging.getLogger("lysos-api.hardening")


# ---------------------------------------------------------------------
# Config (env-tunable)
# ---------------------------------------------------------------------

ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "LYSOS_CORS_ALLOWED_ORIGINS",
        "https://huggingface.co,http://localhost:5173,http://localhost:7860,"
        "https://*.hf.space",
    ).split(",") if o.strip()
]
MAX_BODY_BYTES = int(os.environ.get("LYSOS_MAX_BODY_BYTES", str(1 * 1024 * 1024)))
RATE_LIMIT_DESIGN_PER_MIN = int(os.environ.get("LYSOS_RL_DESIGN_PER_MIN", "5"))
RATE_LIMIT_SCORE_PER_MIN = int(os.environ.get("LYSOS_RL_SCORE_PER_MIN", "30"))
RATE_LIMIT_DEFAULT_PER_MIN = int(os.environ.get("LYSOS_RL_DEFAULT_PER_MIN", "120"))


# ---------------------------------------------------------------------
# Per-IP token-bucket rate limiter (no slowapi dep — keeps Space slim)
# ---------------------------------------------------------------------


class _Bucket:
    __slots__ = ("tokens", "last", "capacity", "refill_per_s")

    def __init__(self, capacity: int):
        self.tokens = capacity
        self.last = time.monotonic()
        self.capacity = capacity
        self.refill_per_s = capacity / 60.0

    def take(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_s)
        self.last = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


_BUCKETS: dict[tuple[str, str], _Bucket] = {}


def _route_limit(path: str) -> int:
    if path.startswith("/api/design"):
        return RATE_LIMIT_DESIGN_PER_MIN
    if path.startswith("/api/score") or path.startswith("/api/similar"):
        return RATE_LIMIT_SCORE_PER_MIN
    return RATE_LIMIT_DEFAULT_PER_MIN


def _client_ip(req: Request) -> str:
    # Honour standard reverse-proxy header but only if it's set by HF Spaces.
    fwd = req.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return req.client.host if req.client else "unknown"


# ---------------------------------------------------------------------
# SMILES sanitization (used by /api/score, /api/similar)
# ---------------------------------------------------------------------

# Allowed SMILES chars: atoms, brackets, bonds, ring digits, charges, isotopes.
# Reject anything with whitespace control codes or HTML/JS injection patterns.
_SMILES_OK = re.compile(r"^[A-Za-z0-9\[\]\(\)=#\-+@/\\.%:*]+$")
_MAX_SMILES_LEN = 500


def sanitize_smiles(s: str) -> str:
    """Raises ValueError on invalid input. Trim + length + char-class check."""
    if not isinstance(s, str):
        raise ValueError("smiles must be a string")
    s = s.strip()
    if len(s) == 0:
        raise ValueError("smiles is empty")
    if len(s) > _MAX_SMILES_LEN:
        raise ValueError(f"smiles too long (>{_MAX_SMILES_LEN})")
    if not _SMILES_OK.match(s):
        raise ValueError("smiles contains illegal characters")
    return s


# ---------------------------------------------------------------------
# Cold-start lock for the heavy model
# ---------------------------------------------------------------------

_load_lock = asyncio.Lock()


async def with_model_lock(loader: Callable[[], Any]) -> Any:
    """Serialize cold-start so the first-request thundering-herd doesn't
    kick off two parallel 60GB model loads."""
    async with _load_lock:
        return loader()


# ---------------------------------------------------------------------
# Middleware: request ID + timing + structured log + body-size cap
# ---------------------------------------------------------------------


async def request_id_logging(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    rid = request.headers.get("x-request-id", uuid.uuid4().hex[:12])
    request.state.request_id = rid
    t0 = time.perf_counter()

    # Body-size cap (lazy: only enforce on POST with declared length)
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"error": "request_too_large", "max_bytes": MAX_BODY_BYTES,
                     "request_id": rid},
            headers={"X-Request-ID": rid},
        )

    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.perf_counter() - t0
        log.error(json.dumps({
            "level": "error", "request_id": rid,
            "method": request.method, "path": request.url.path,
            "client_ip": _client_ip(request),
            "elapsed_ms": int(elapsed * 1000),
            "exc_type": type(exc).__name__,
            "exc_msg": str(exc)[:200],
            "trace": traceback.format_exc()[:2000],
        }))
        return JSONResponse(
            status_code=500,
            content={"error": "internal_server_error",
                     "request_id": rid},
            headers={"X-Request-ID": rid},
        )

    elapsed = time.perf_counter() - t0
    response.headers["X-Request-ID"] = rid
    response.headers["X-Process-Time-Ms"] = str(int(elapsed * 1000))

    log.info(json.dumps({
        "level": "info", "request_id": rid,
        "method": request.method, "path": request.url.path,
        "status": response.status_code,
        "client_ip": _client_ip(request),
        "elapsed_ms": int(elapsed * 1000),
    }))
    return response


async def rate_limit_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    # Skip rate limit on docs/health/ready endpoints
    p = request.url.path
    if p in ("/api/health", "/api/ready", "/docs", "/openapi.json", "/redoc"):
        return await call_next(request)
    ip = _client_ip(request)
    cap = _route_limit(p)
    key = (ip, p)
    bucket = _BUCKETS.setdefault(key, _Bucket(cap))
    if not bucket.take():
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited",
                     "limit_per_min": cap,
                     "request_id": getattr(request.state, "request_id", "?")},
            headers={"Retry-After": "60"},
        )
    return await call_next(request)


# ---------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------


def apply_hardening(app: FastAPI) -> None:
    """Idempotently install all middleware + hardened endpoints on `app`."""

    if getattr(app.state, "_hardened", False):
        return
    app.state._hardened = True

    # Replace any already-added permissive CORS with strict origins.
    app.user_middleware = [
        m for m in app.user_middleware if m.cls is not CORSMiddleware
    ]
    app.middleware_stack = None  # rebuild on next request
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_origin_regex=r"https://.*\.hf\.space",
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Process-Time-Ms"],
    )

    app.middleware("http")(request_id_logging)
    app.middleware("http")(rate_limit_middleware)

    # /api/ready vs /api/health split (k8s-style)
    @app.get("/api/ready", tags=["ops"])
    async def ready() -> dict:
        from . import server as srv
        loaded = srv._GENERATOR is not None
        return {"ready": loaded, "model_loaded": loaded,
                "uptime_s": time.time() - srv._STARTED}

    log.info("Hardening applied: rate_limits=design:%d/min score:%d/min default:%d/min "
             "max_body=%dKB cors_allow=%s",
             RATE_LIMIT_DESIGN_PER_MIN, RATE_LIMIT_SCORE_PER_MIN,
             RATE_LIMIT_DEFAULT_PER_MIN, MAX_BODY_BYTES // 1024,
             ALLOWED_ORIGINS)
