"""
session.py — In-memory session/conversation manager.
Stores conversation history and pending confirmation state per session_id.
A session belongs to the customer who started it.
"""
from threading import Lock
from typing import Optional

# session_id -> {customer_id, messages: [], pending: dict|None}
_sessions: dict[str, dict] = {}
_lock = Lock()


def get_or_create_session(session_id: str, customer_id: str) -> dict:
    """
    Get existing session or create new one.
    Raises ValueError if session belongs to a different customer (403 case).
    """
    with _lock:
        if session_id not in _sessions:
            _sessions[session_id] = {
                "customer_id": customer_id,
                "messages": [],
                "pending": None,  # pending_confirmation state
            }
        session = _sessions[session_id]
        if session["customer_id"] != customer_id:
            raise PermissionError(f"Session {session_id} belongs to another customer.")
        return session


def append_message(session_id: str, role: str, content) -> None:
    """Append a message to session history."""
    with _lock:
        _sessions[session_id]["messages"].append({"role": role, "content": content})


def get_history(session_id: str) -> list[dict]:
    """Return conversation history for this session."""
    with _lock:
        return list(_sessions[session_id]["messages"])


def set_pending(session_id: str, pending: Optional[dict]) -> None:
    """Store or clear a pending confirmation proposal."""
    with _lock:
        _sessions[session_id]["pending"] = pending


def get_pending(session_id: str) -> Optional[dict]:
    """Get the current pending proposal (or None)."""
    with _lock:
        return _sessions[session_id].get("pending")
