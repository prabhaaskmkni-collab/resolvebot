import uuid
import time
import re
import html
from collections import defaultdict
from fastapi import FastAPI, Request, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from typing import Optional

from config import APP_TODAY_STR
from db.queries import get_customer_by_id
from session import get_or_create_session, append_message, get_history, set_pending, get_pending
from agent import run_agent

# Debug mode explicitly OFF for security
app = FastAPI(
    title="ResolveBot",
    description="AI customer support assistant for ShopSphere",
    version="1.0.0",
    debug=False,
)


# ── Security Headers Middleware ───────────────────────────────────────────────

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Attach OWASP recommended security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    # Allow Swagger UI (/docs) to load assets from jsdelivr CDN
    if request.url.path.startswith(("/docs", "/openapi.json", "/redoc")):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com;"
        )
    else:
        response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response


# ── In-Memory Rate Limiting (120 req/minute per client) ──────────────────────

_request_timestamps: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX_REQUESTS = 120
RATE_LIMIT_WINDOW_SECONDS = 60.0

@app.middleware("http")
async def rate_limiting_middleware(request: Request, call_next):
    """Prevent DDoS and brute force while allowing rapid automated tests."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    
    # Prune old timestamps
    timestamps = [t for t in _request_timestamps[client_ip] if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(timestamps) >= RATE_LIMIT_MAX_REQUESTS:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Too many requests. Please try again in a moment."}
        )
    timestamps.append(now)
    _request_timestamps[client_ip] = timestamps

    return await call_next(request)


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "ResolveBot API",
        "message": "ResolveBot is running! Use POST /chat or open /docs to interact.",
        "docs_url": "http://127.0.0.1:8000/docs",
        "chat_endpoint": "http://127.0.0.1:8000/chat (POST)"
    }


# ── Sanitized Request / Response Models ───────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=4000)

    @validator("session_id", "message")
    def sanitize_input(cls, v: str) -> str:
        # Strip null bytes and normalize whitespace
        cleaned = v.replace("\x00", "").strip()
        # Escape potential XSS payload characters
        cleaned = html.escape(cleaned)
        return cleaned


class ChatResponse(BaseModel):
    request_id: str
    answer: str
    route: str
    citations: list
    tool_calls: list
    pending_confirmation: bool


# ── Main chat endpoint ────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(
    body: ChatRequest,
    x_customer_id: Optional[str] = Header(default=None),
):
    # ── Auth checks ───────────────────────────────────────────────────────────
    if not x_customer_id:
        raise HTTPException(status_code=401, detail="X-Customer-Id header is required.")

    customer = get_customer_by_id(x_customer_id)
    if not customer:
        raise HTTPException(status_code=401, detail="Unknown customer ID.")

    # ── Session ownership check ───────────────────────────────────────────────
    try:
        session = get_or_create_session(body.session_id, x_customer_id)
    except PermissionError:
        raise HTTPException(status_code=403, detail="This session belongs to another customer.")

    # ── Get conversation state ────────────────────────────────────────────────
    history = get_history(body.session_id)
    pending = get_pending(body.session_id)

    # ── Run agent ─────────────────────────────────────────────────────────────
    result = run_agent(
        customer_id=x_customer_id,
        message=body.message,
        history=history,
        pending=pending,
    )

    # ── Update session history ────────────────────────────────────────────────
    append_message(body.session_id, "user", body.message)
    append_message(body.session_id, "assistant", result["answer"])
    set_pending(body.session_id, result.get("new_pending"))

    # ── Return response ───────────────────────────────────────────────────────
    return JSONResponse(content={
        "request_id": str(uuid.uuid4()),
        "answer": result["answer"],
        "route": result["route"],
        "citations": result["citations"],
        "tool_calls": result["tool_calls"],
        "pending_confirmation": result["pending_confirmation"],
    })


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "app_today": APP_TODAY_STR}


# ── Validation error handler → 400 ───────────────────────────────────────────

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"detail": "Invalid request body. Required fields: session_id, message."}
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Prevent internal server tracebacks from leaking to clients."""
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please contact support."}
    )
