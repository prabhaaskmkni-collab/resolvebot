"""
config.py — Central configuration loaded from environment variables.
All business numbers come from policy_parameters DB, NOT from here.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── File Paths ────────────────────────────────────────────────────────────────
POLICIES_PATH: str = os.getenv("POLICIES_PATH", "./data/policies.md")
MANIFEST_PATH: str = os.getenv("MANIFEST_PATH", "./data/manifest.json")
DB_PATH: str = os.getenv("DB_PATH", "./data/shopsphere.db")

# ── Simulated "today" — NEVER use datetime.date.today() for business logic ───
APP_TODAY_STR: str = os.getenv("APP_TODAY", "2026-07-01")

# ── LLM Settings ──────────────────────────────────────────────────────────────
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai").lower()

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_MODEL: str = os.getenv("GOOGLE_MODEL", "gemini-3.5-flash-lite")

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")

# Max tool calls per message turn (safety limit)
MAX_TOOL_CALLS: int = int(os.getenv("MAX_TOOL_CALLS", "6"))
