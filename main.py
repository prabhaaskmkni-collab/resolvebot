"""
main.py — FastAPI entry point for ResolveBot.
One endpoint: POST /chat on port 8000.
Header: X-Customer-Id (required)
"""
import uuid
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from config import APP_TODAY_STR
from db.queries import get_customer_by_id
from session import get_or_create_session, append_message, get_history, set_pending, get_pending
from agent import run_agent

app = FastAPI(
    title="ResolveBot",
    description="AI customer support assistant for ShopSphere",
    version="1.0.0",
)


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "ResolveBot API",
        "message": "ResolveBot is running! Use POST /chat or open /docs to interact.",
        "docs_url": "http://127.0.0.1:8000/docs",
        "chat_endpoint": "http://127.0.0.1:8000/chat (POST)"
    }



# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str
    message: str


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

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"detail": "Invalid request body. Required fields: session_id, message."}
    )
