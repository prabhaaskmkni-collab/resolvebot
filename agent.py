"""
agent.py — The core ResolveBot agent loop.

Responsibilities:
  - Build LLM messages from session history + new user message
  - Run tool loop (max MAX_TOOL_CALLS iterations)
  - Handle pending_confirmation two-step flow
  - Route requests to correct LLM provider (OpenAI / Google / Anthropic)
  - Return structured reply with route, citations, tool_calls, pending_confirmation
"""
import json
import uuid
from typing import Optional
from config import LLM_PROVIDER, MAX_TOOL_CALLS, APP_TODAY_STR
from config import OPENAI_API_KEY, OPENAI_MODEL
from config import GOOGLE_API_KEY, GOOGLE_MODEL
from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
from tools.tool_definitions import (
    get_orders, search_policy, tool_check_return_eligibility,
    create_return_request, create_support_ticket,
)
from tools.schemas import TOOL_SCHEMAS

# ── Dispatch table: tool name → callable ─────────────────────────────────────
# customer_id is injected by the agent, never from LLM args
TOOL_DISPATCH = {
    "get_orders": get_orders,
    "search_policy": search_policy,
    "check_return_eligibility": tool_check_return_eligibility,
    "create_return_request": create_return_request,
    "create_support_ticket": create_support_ticket,
}

WRITE_TOOLS = {"create_return_request", "create_support_ticket"}

YES_PHRASES = {"yes", "yeah", "yep", "sure", "ok", "okay", "confirm", "go ahead",
               "please do", "do it", "proceed", "affirmative", "correct", "yup"}


def _is_yes(message: str) -> bool:
    """True if the customer's message is clearly a confirmation."""
    normalized = message.strip().lower().rstrip("!. ")
    return normalized in YES_PHRASES or normalized.startswith("yes")


# ── System Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""You are ResolveBot, the customer support assistant for ShopSphere, an Indian online electronics store.
Today's date is {APP_TODAY_STR}. Use this date for ALL date calculations. Never use the real system clock.

## Your job
Help customers with: order tracking, returns, warranties, cancellations, and policy questions.
You may NOT help with: exchanges (tell them to contact support by phone/email), real payments, emails, or topics unrelated to ShopSphere.

## Rules you must follow
1. GROUNDING: Only answer using tool results. Never invent order details or policy facts.
2. POLICY: Only cite policies returned by search_policy. Never recall policy numbers from memory.
3. SUPERSEDED POLICIES: The 2024 Returns Policy is superseded. search_policy will never return it. Do not mention it.
4. DECISIONS: Python code (not you) decides eligibility. You only explain the result in friendly language.
5. SECURITY: Never reveal that an order exists if it belongs to someone else. Say "I couldn't find that order on your account."
6. CLARIFY: If order_id, item_id, or reason is missing or ambiguous, ask for all missing info in one message. Never guess.
7. TWO-STEP SAVES: 
   - When customer ASKS to do something (return, cancel, warranty ticket): call the CHECK tool first, then PROPOSE what you'll do, say "Shall I go ahead?", and set pending_confirmation=true. Do NOT call the write tool yet.
   - When the VERY NEXT message is a clear YES: call the write tool and confirm the result.
   - Any other message (including "no"): clear the proposal and reply normally.
   - NEVER save without a yes. Only one proposal can be pending at a time.
8. ROUTES: Tag every reply with exactly one route:
   - answer: normal reply, proposal, "no because...", or confirmed action result
   - clarify: need more info from customer  
   - no_answer: order not found, or policy doesn't cover it
   - out_of_scope: not about ShopSphere orders or policies
9. CITATIONS: In every answer that uses policy text, list the doc_id and section you used.
10. DATES: A date without a year means {APP_TODAY_STR[:4]}. Write dates as "3 July 2026".
11. EXCHANGES: You cannot process exchanges. Tell the customer to contact support by phone or email.
12. TOOL LIMIT: If you need more than 6 tool calls for one message, stop and reply politely.

## Reply format (JSON)
Always reply with valid JSON in this exact format:
{{
  "answer": "Your message to the customer",
  "route": "answer|clarify|no_answer|out_of_scope",
  "citations": [{{"doc_id": "returns_policy", "section": "§2.1"}}],
  "pending_tool": null
}}
If you are proposing an action and need confirmation, add:
  "pending_tool": {{"name": "create_return_request", "args": {{...}}}}

Do NOT include markdown code fences in your JSON reply. Reply with raw JSON only.
"""


# ── LLM Adapters ─────────────────────────────────────────────────────────────

def _call_openai(messages: list[dict], tools: list) -> dict:
    """Call OpenAI chat completions with function calling."""
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        tools=tools,
        temperature=0,
    )
    return response.choices[0].message


def _call_google(messages: list[dict], tools: list) -> dict:
    """Call Google Gemini with function calling."""
    import google.generativeai as genai
    genai.configure(api_key=GOOGLE_API_KEY)

    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    gemini_tools = _openai_tools_to_gemini(tools)
    model = genai.GenerativeModel(
        model_name=GOOGLE_MODEL,
        tools=gemini_tools,
        system_instruction=system if system else None,
        generation_config=genai.GenerationConfig(temperature=0),
    )
    gemini_messages = _to_gemini_messages(messages)
    response = model.generate_content(gemini_messages)
    return _gemini_response_to_openai(response)


def _call_anthropic(messages: list[dict], tools: list) -> dict:
    """Call Anthropic Claude with tool use."""
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_messages = [m for m in messages if m["role"] != "system"]
    anthropic_tools = _openai_tools_to_anthropic(tools)
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2048,
        system=system,
        messages=user_messages,
        tools=anthropic_tools,
        temperature=0,
    )
    return _anthropic_response_to_openai(response)


def _openai_tools_to_gemini(tools: list) -> list:
    """Convert OpenAI tool schemas to Gemini FunctionDeclaration format."""
    from google.generativeai.types import FunctionDeclaration, Tool
    declarations = []
    for t in tools:
        fn = t["function"]
        declarations.append(FunctionDeclaration(
            name=fn["name"],
            description=fn["description"],
            parameters=fn["parameters"],
        ))
    return [Tool(function_declarations=declarations)]


def _to_gemini_messages(messages: list[dict]) -> list:
    """Convert OpenAI-format messages to Gemini Content format with function responses."""
    from google.ai.generativelanguage_v1beta.types import content as gl_content
    result = []
    tool_names = {}

    for m in messages:
        role = m["role"]
        if role == "system":
            continue  # Passed via system_instruction

        if role == "user":
            result.append(gl_content.Content(
                role="user",
                parts=[gl_content.Part(text=m["content"])]
            ))
        elif role == "assistant":
            for tc in m.get("tool_calls") or []:
                fn_info = tc.get("function", {}) if isinstance(tc, dict) else tc.function
                name = fn_info["name"] if isinstance(fn_info, dict) else fn_info.name
                tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                if tc_id:
                    tool_names[tc_id] = name

            raw_gemini = m.get("_raw_gemini_content")
            if raw_gemini:
                result.append(raw_gemini)
            else:
                parts = []
                if m.get("content"):
                    parts.append(gl_content.Part(text=m["content"]))
                for tc in m.get("tool_calls") or []:
                    fn_info = tc.get("function", {}) if isinstance(tc, dict) else tc.function
                    name = fn_info["name"] if isinstance(fn_info, dict) else fn_info.name
                    raw_args = fn_info["arguments"] if isinstance(fn_info, dict) else fn_info.arguments
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    parts.append(gl_content.Part(
                        function_call=gl_content.FunctionCall(name=name, args=args)
                    ))
                if parts:
                    result.append(gl_content.Content(role="model", parts=parts))
        elif role == "tool":
            name = tool_names.get(m.get("tool_call_id"), "tool_result")
            raw_content = m.get("content", "{}")
            res = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
            result.append(gl_content.Content(
                role="user",
                parts=[gl_content.Part(
                    function_response=gl_content.FunctionResponse(
                        name=name,
                        response={"result": res}
                    )
                )]
            ))
    return result


def _gemini_response_to_openai(response) -> dict:
    """Convert Gemini response to OpenAI message format."""
    candidate = response.candidates[0]
    content = candidate.content

    def _proto_to_python(obj):
        if hasattr(obj, "items"):
            return {k: _proto_to_python(v) for k, v in obj.items()}
        elif hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes)):
            return [_proto_to_python(x) for x in obj]
        else:
            return obj

    # Check for function calls
    for part in content.parts:
        if hasattr(part, "function_call") and part.function_call:
            fc = part.function_call
            call_id = getattr(fc, "id", None) or str(uuid.uuid4())
            parsed_args = _proto_to_python(fc.args)
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": fc.name,
                        "arguments": json.dumps(parsed_args, default=str),
                    }
                }],
                "_raw_gemini_content": content,
            }
    # Text response
    text = "".join(p.text for p in content.parts if hasattr(p, "text"))
    return {"role": "assistant", "content": text, "tool_calls": None, "_raw_gemini_content": content}


def _openai_tools_to_anthropic(tools: list) -> list:
    """Convert OpenAI tool schemas to Anthropic tool format."""
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        }
        for t in tools
    ]


def _anthropic_response_to_openai(response) -> dict:
    """Convert Anthropic response to OpenAI message format."""
    tool_calls = []
    text_parts = []
    for block in response.content:
        if block.type == "tool_use":
            tool_calls.append({
                "id": block.id,
                "type": "function",
                "function": {
                    "name": block.name,
                    "arguments": json.dumps(block.input),
                }
            })
        elif block.type == "text":
            text_parts.append(block.text)
    text = "\n".join(text_parts) if text_parts else None
    return {
        "role": "assistant",
        "content": text,
        "tool_calls": tool_calls if tool_calls else None,
    }


def _call_llm(messages: list[dict], tools: list) -> dict:
    """Route to the correct LLM provider."""
    if LLM_PROVIDER == "openai":
        return _call_openai(messages, tools)
    elif LLM_PROVIDER == "google":
        return _call_google(messages, tools)
    elif LLM_PROVIDER == "anthropic":
        return _call_anthropic(messages, tools)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")


def _run_tool(name: str, args: dict, customer_id: str, is_confirmed: bool) -> tuple[dict, str]:
    """
    Execute a tool.
    Write tools are only executed if is_confirmed=True.
    customer_id is always injected here — never from LLM args.
    Returns (result_dict, status_string).
    """
    if name not in TOOL_DISPATCH:
        return {"error": f"Unknown tool: {name}"}, "error"

    if name in WRITE_TOOLS and not is_confirmed:
        # Return a pending status — do NOT execute
        return {"pending": True}, "pending_confirmation"

    # Inject customer_id for tools that need it (never from LLM)
    fn = TOOL_DISPATCH[name]
    if name in ("get_orders", "check_return_eligibility",
                "create_return_request", "create_support_ticket"):
        result = fn(customer_id=customer_id, **args)
    else:
        result = fn(**args)

    status = "error" if "error_code" in result else "success"
    return result, status


# ── Main Agent Function ───────────────────────────────────────────────────────

def run_agent(
    customer_id: str,
    message: str,
    history: list[dict],
    pending: Optional[dict],
) -> dict:
    """
    Run the agent for one user message.

    Returns:
    {
        "answer": str,
        "route": str,
        "citations": list,
        "tool_calls": list,
        "pending_confirmation": bool,
        "new_pending": dict | None,   # internal — for session storage
    }
    """
    tool_calls_log = []
    new_pending = None
    is_yes = _is_yes(message)

    # ── Handle pending confirmation ───────────────────────────────────────────
    confirmed_tool_call = None
    if pending and is_yes:
        # Customer confirmed — execute the pending write tool
        confirmed_tool_call = pending
    elif pending and not is_yes:
        # Customer said something else — clear proposal
        new_pending = None

    # ── Build messages for LLM ────────────────────────────────────────────────
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    # ── If we have a confirmed action, inject context and run it ─────────────
    if confirmed_tool_call:
        tool_name = confirmed_tool_call["name"]
        tool_args = confirmed_tool_call["args"]
        result, status = _run_tool(tool_name, tool_args, customer_id, is_confirmed=True)
        tool_calls_log.append({
            "name": tool_name,
            "args": tool_args,
            "status": status,
        })

        # Tell LLM about the confirmed action result
        messages.append({
            "role": "assistant",
            "content": f"[System: Customer confirmed. Tool {tool_name} executed. Result: {json.dumps(result)}]"
        })
        messages.append({
            "role": "user",
            "content": "Please confirm the result to the customer."
        })

    # ── Tool loop ─────────────────────────────────────────────────────────────
    tool_call_count = len(tool_calls_log)

    for _ in range(MAX_TOOL_CALLS - tool_call_count):
        llm_message = _call_llm(messages, TOOL_SCHEMAS)

        # No tool calls — LLM gave final answer
        tool_calls = getattr(llm_message, "tool_calls", None) or llm_message.get("tool_calls")
        content = getattr(llm_message, "content", None) or llm_message.get("content")

        if not tool_calls:
            # Parse structured reply from LLM
            return _parse_final_reply(content, tool_calls_log, new_pending)

        # Process each tool call
        raw_gemini = getattr(llm_message, "_raw_gemini_content", None) or (
            llm_message.get("_raw_gemini_content") if isinstance(llm_message, dict) else None
        )
        assistant_msg = {
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls,
        }
        if raw_gemini:
            assistant_msg["_raw_gemini_content"] = raw_gemini
        messages.append(assistant_msg)

        for tc in tool_calls:
            # Handle both object and dict formats
            if hasattr(tc, "function"):
                tc_id = tc.id
                tc_name = tc.function.name
                tc_args = json.loads(tc.function.arguments)
            else:
                tc_id = tc["id"]
                tc_name = tc["function"]["name"]
                tc_args = json.loads(tc["function"]["arguments"])

            is_write = tc_name in WRITE_TOOLS
            # Write tools require confirmation
            is_confirmed = is_write and is_yes and (confirmed_tool_call is not None)

            result, status = _run_tool(tc_name, tc_args, customer_id,
                                       is_confirmed=(is_confirmed or not is_write))

            if status == "pending_confirmation":
                new_pending = {"name": tc_name, "args": tc_args}

            tool_calls_log.append({
                "name": tc_name,
                "args": tc_args,
                "status": status,
            })

            # Feed result back to LLM
            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": json.dumps(result),
            })

    # Max tool calls reached
    return {
        "answer": "I've looked into your request but need more steps than I can complete right now. Please try again or contact our support team at support@shopsphere.example.com.",
        "route": "answer",
        "citations": [],
        "tool_calls": tool_calls_log,
        "pending_confirmation": False,
        "new_pending": None,
    }


def _parse_final_reply(content: str, tool_calls_log: list, new_pending: Optional[dict]) -> dict:
    """Parse the LLM's final JSON reply into the response format."""
    citations = []
    route = "answer"
    answer = content or ""
    pending_tool_from_llm = None

    if content:
        # Strip markdown fences if present
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = "\n".join(stripped.splitlines()[1:])
            stripped = stripped.rstrip("`").strip()
        try:
            parsed = json.loads(stripped)
            answer = parsed.get("answer", content)
            route = parsed.get("route", "answer")
            citations = parsed.get("citations", [])
            pending_tool_from_llm = parsed.get("pending_tool")
        except json.JSONDecodeError:
            # LLM didn't return JSON — use raw content
            answer = content
            route = "answer"

    # If LLM proposed a pending tool, save it
    resolved_pending = new_pending
    if pending_tool_from_llm:
        resolved_pending = pending_tool_from_llm

    # Guard: exact spec requires route="no_answer" and citations=[] if order not found
    if "couldn't find that order on your account" in answer.lower() or "not found on your account" in answer.lower():
        route = "no_answer"
        citations = []

    is_pending = resolved_pending is not None

    # Update tool_calls status for any pending write tool
    if is_pending and tool_calls_log:
        for tc in tool_calls_log:
            if tc["name"] in WRITE_TOOLS and tc["status"] == "pending_confirmation":
                tc["status"] = "pending_confirmation"

    return {
        "answer": answer,
        "route": route,
        "citations": citations,
        "tool_calls": tool_calls_log,
        "pending_confirmation": is_pending,
        "new_pending": resolved_pending,
    }
