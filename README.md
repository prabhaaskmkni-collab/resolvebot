# ResolveBot — AI Customer Support Assistant for ShopSphere

A chat-based support assistant that helps ShopSphere customers with order tracking, returns, warranties, cancellations, and policy questions.

---

## Quick Start

### 1. Prerequisites

- Python 3.10+
- An API key from **OpenAI**, **Google Gemini**, or **Anthropic**

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set:

```env
LLM_PROVIDER=openai          # or: google, anthropic
OPENAI_API_KEY=sk-...        # fill in your key
APP_TODAY=2026-07-01         # simulated "today" date
```

### 4. Start the server

```bash
uvicorn main:app --port 8000
```

Or with auto-reload for development:
```bash
uvicorn main:app --port 8000 --reload
```

The service is now live at `http://localhost:8000`.

---

## API Reference

### `POST /chat`

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-Customer-Id` | ✅ | The logged-in customer's ID (e.g. `C1009`) |
| `Content-Type` | ✅ | `application/json` |

**Request body:**
```json
{
  "session_id": "s1",
  "message": "Where is my order SS-10512?"
}
```

**Response:**
```json
{
  "request_id": "uuid",
  "answer": "Your order SS-10512 is currently in transit...",
  "route": "answer",
  "citations": [{"doc_id": "shipping_policy", "section": "§3.1"}],
  "tool_calls": [
    {"name": "get_orders", "args": {"order_id": "SS-10512"}, "status": "success"}
  ],
  "pending_confirmation": false
}
```

**Routes:**
| Route | Meaning |
|-------|---------|
| `answer` | Normal reply, proposal, refusal, or confirmed action |
| `clarify` | More info needed from customer |
| `no_answer` | Order not found or policy doesn't cover it |
| `out_of_scope` | Not about ShopSphere orders or policies |

**HTTP error codes:**
| Code | Reason |
|------|--------|
| 400 | Missing `session_id` or `message` |
| 401 | Missing or unknown `X-Customer-Id` |
| 403 | `session_id` belongs to another customer |

---

## How It Works

### Tools
The agent can call exactly 5 tools (exact names required by the test harness):

| Tool | Purpose |
|------|---------|
| `get_orders` | Fetch orders, items, shipment status, and computed warranty/delivery info |
| `search_policy` | Retrieve matching policy sections (current only, never superseded) |
| `check_return_eligibility` | Python-code decision on whether items can be returned |
| `create_return_request` | Write a return to the DB (only after customer says yes) |
| `create_support_ticket` | Write a warranty or cancellation ticket (only after yes) |

### Policy Search (RAG)
- `policies.md` is parsed into 10 sections by `#` heading
- Each section is matched to `manifest.json` by `doc_id`
- Only documents with `status = "current"` **and** `effective_date <= APP_TODAY` are searchable
- The superseded 2024 Returns Policy is **never** returned
- Future-dated policies (e.g., new shipping fees from Aug 2026) are noted as upcoming changes

### The Two-Step Confirmation Flow
1. Customer asks for an action (return, cancel, warranty ticket)
2. Bot checks eligibility → proposes the action → asks "Shall I go ahead?" → sets `pending_confirmation: true` — **nothing is saved**
3. Customer replies with a clear YES → bot executes the write tool → confirms result
4. Any other reply → proposal is cleared

### Business Rules (Python, not LLM)
- All numbers (return window, warranty months) come from the `policy_parameters` DB table — never hardcoded
- Return window: `days_since_delivery ≤ return_window_days` (day 30 is the last allowed day)
- Warranty: uses `dateutil.relativedelta` for correct month arithmetic (handles end-of-month edge cases)
- Cancellation: only allowed when `order.status = "processing"`

---

## Environment Variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `POLICIES_PATH` | `./data/policies.md` | Path to policy documents |
| `MANIFEST_PATH` | `./data/manifest.json` | Path to policy manifest |
| `DB_PATH` | `./data/shopsphere.db` | Path to SQLite database |
| `APP_TODAY` | `2026-07-01` | Simulated "today" date |
| `LLM_PROVIDER` | `openai` | `openai`, `google`, or `anthropic` |
| `OPENAI_API_KEY` | — | Your OpenAI key |
| `GOOGLE_API_KEY` | — | Your Google Gemini key |
| `GOOGLE_MODEL` | `gemini-3.5-flash-lite` | Google Gemini model name |
| `ANTHROPIC_API_KEY` | — | Your Anthropic key |

---

## Example Conversations

### Track an order
```
POST /chat
X-Customer-Id: C1009

{"session_id": "s1", "message": "Where is order SS-10512?"}

→ "Your order SS-10512 is currently in transit. The estimated delivery date is 3 July 2026."
```

### Return request (two steps)
```
Message 1: "Return the speaker from SS-10458, I changed my mind."
Reply 1:   "The Nimbra Smart Speaker is eligible for return (delivered 10 days ago, within the 30-day window).
            Shall I create the return request?"
            pending_confirmation: true

Message 2: "Yes, go ahead."
Reply 2:   "Done! Return request created (ID: abc-123). We'll send a pickup slot by SMS within one business day."
            pending_confirmation: false
```

### Policy question
```
"How long do I have to return something?"
→ "You have 30 days from the delivery date to return most items..."
   citations: [{"doc_id": "returns_policy", "section": "§2.1"}]
```

### Out of scope
```
"What's the weather like?"
→ "I'm only able to help with ShopSphere orders and policies."
   route: "out_of_scope"
```

---

## Assumptions

1. **APP_TODAY is authoritative** — the real system clock is never used for business logic.
2. **`policy_parameters` table is source of truth** — all numbers (30-day window, warranty months) are read from DB, never hardcoded. This means the test harness can swap these values and the agent will adapt.
3. **Exchanges are out of scope** — the task explicitly lists exchanges as "not needed". The bot tells customers to contact support by phone/email.
4. **Session storage is in-memory** — sessions reset if the server restarts. This is intentional for the MVP; production would use Redis.
5. **Damage within 48 hours** — the bot handles this via the defective reason code; the exact 48-hour window counting logic is covered by `check_return_eligibility` with reason=defective.
6. **`search_policy` keyword matching** — a simple token-frequency search is used. This is sufficient for the structured policy documents and avoids requiring a local embedding model or external vector DB.

---

## What Does Not Work Yet

- No persistent session storage (in-memory only; resets on restart)
- No embedding-based semantic search (using keyword scoring instead)
- Damage-on-arrival 48-hour window is not separately enforced in `check_return_eligibility` — it falls under the defective reason

---

## AI Assistance

This project was built with the assistance of Google Antigravity (AI coding assistant). The architecture, business logic, and all decisions about eligibility rules were designed and reviewed by the developer. All tool implementations were verified against the TASK specification manually.

---

## Project Structure

```
resolvebot/
├── main.py                  # FastAPI app + /chat endpoint
├── agent.py                 # LLM agent loop, tool dispatch, confirmation flow
├── session.py               # In-memory session manager
├── config.py                # Environment variables
├── requirements.txt
├── .env.example
├── db/
│   ├── connection.py        # SQLite connection
│   └── queries.py           # All SQL queries
├── tools/
│   ├── business_rules.py    # All eligibility logic in Python
│   ├── tool_definitions.py  # 5 tool functions
│   └── schemas.py           # OpenAI tool schemas for LLM
├── policies/
│   └── loader.py            # Parse + filter + search policies
└── data/                    # Provided data (not committed)
```
