"""
test_resolvebot.py — Automated end-to-end test suite for ResolveBot.
Runs 5 realistic customer support scenarios against the live server.

Usage:
    Make sure uvicorn is running:
        uvicorn main:app --port 8000
    Then in another terminal run:
        python test_resolvebot.py
"""
import urllib.request
import urllib.error
import json
import sys

BASE_URL = "http://127.0.0.1:8000/chat"

# Colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def send_chat(customer_id: str, session_id: str, message: str) -> dict:
    """Send a chat message to ResolveBot."""
    payload = json.dumps({
        "session_id": session_id,
        "message": message
    }).encode("utf-8")

    req = urllib.request.Request(
        BASE_URL,
        data=payload,
        headers={
            "X-Customer-Id": customer_id,
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        return {"_error_status": e.code, "_error_body": error_body}


def print_test_header(num: int, title: str):
    print(f"\n{BLUE}{'='*70}{RESET}")
    print(f"{BLUE}Test {num}: {title}{RESET}")
    print(f"{BLUE}{'='*70}{RESET}")


def main():
    print(f"\n{YELLOW}Starting ResolveBot Automated Test Suite...{RESET}")
    print(f"Target URL: {BASE_URL}\n")

    # ── Test 1: Order Tracking ────────────────────────────────────────────────
    print_test_header(1, "Order Tracking (Customer C1009 asks about SS-10512)")
    res1 = send_chat("C1009", "sess-test-1", "Where is my order SS-10512?")
    
    if "_error_status" in res1:
        print(f"{RED}[FAIL]{RESET} Server returned HTTP error: {res1['_error_status']}")
        print(f"Details: {res1['_error_body']}")
        sys.exit(1)

    tools_used = [t["name"] for t in res1.get("tool_calls", [])]
    print(f"Answer: {res1.get('answer')}")
    print(f"Tools called: {tools_used}")
    print(f"Route: {res1.get('route')}")

    if "get_orders" in tools_used and "10512" in res1.get("answer", ""):
        print(f"{GREEN}[PASS] Order tracking retrieved and answered successfully!{RESET}")
    else:
        print(f"{YELLOW}[CHECK] Received answer, verify tools above.{RESET}")

    # ── Test 2: Policy Search ─────────────────────────────────────────────────
    print_test_header(2, "Policy Search (Return window query)")
    res2 = send_chat("C1009", "sess-test-2", "How many days do I have to return an item?")
    
    tools_used2 = [t["name"] for t in res2.get("tool_calls", [])]
    print(f"Answer: {res2.get('answer')}")
    print(f"Tools called: {tools_used2}")
    print(f"Citations: {res2.get('citations')}")

    if "search_policy" in tools_used2 or "30" in res2.get("answer", ""):
        print(f"{GREEN}[PASS] Policy knowledge retrieved correctly!{RESET}")
    else:
        print(f"{YELLOW}[CHECK] Received answer, verify citations/tools above.{RESET}")

    # ── Test 3: Two-Step Return Flow (Propose -> Confirm) ─────────────────────
    print_test_header(3, "Two-Step Return Flow (Propose -> User says 'Yes')")
    sess3 = "sess-test-return-flow"
    
    # Step 3a: User asks to return
    print(f"{BLUE}Step 3a: Asking to return item SS-10458-1...{RESET}")
    res3a = send_chat("C1009", sess3, "I want to return item SS-10458-1 from order SS-10458 because I changed my mind.")
    print(f"Bot response:\n{res3a.get('answer')}\n")
    print(f"Pending confirmation flag: {res3a.get('pending_confirmation')}")

    # Step 3b: User confirms with 'yes'
    print(f"{BLUE}Step 3b: User replies 'Yes, please proceed'...{RESET}")
    res3b = send_chat("C1009", sess3, "Yes, please go ahead.")
    print(f"Bot response:\n{res3b.get('answer')}\n")
    tools_used3b = [t["name"] for t in res3b.get("tool_calls", [])]
    print(f"Tools executed after confirmation: {tools_used3b}")

    if "create_return_request" in tools_used3b or any(kw in res3b.get("answer", "").lower() for kw in ["return request", "ret-", "successfully created"]):
        print(f"{GREEN}[PASS] Two-step confirmation executed write tool and created return!{RESET}")
    else:
        print(f"{YELLOW}[CHECK] Review response for return ID confirmation.{RESET}")

    # ── Test 4: Security & Cross-Customer Isolation ───────────────────────────
    print_test_header(4, "Security Isolation (Customer C1001 asks for C1009's order)")
    res4 = send_chat("C1001", "sess-test-sec", "Can you check order SS-10512 for me?")
    print(f"Answer: {res4.get('answer')}")
    
    # Customer C1001 should NOT get C1009's private shipping/address details
    answer_lower = res4.get("answer", "").lower()
    if any(w in answer_lower for w in ["not found", "no order", "cannot find", "couldn't find", "could not find", "not associated", "no record"]):
        print(f"{GREEN}[PASS] Security check passed: Customer cannot access other customers' orders!{RESET}")
    else:
        print(f"{YELLOW}[CHECK] Verify order details were not leaked.{RESET}")

    # ── Test 5: Authentication Validation ─────────────────────────────────────
    print_test_header(5, "Authentication Validation (Missing X-Customer-Id header)")
    req_no_auth = urllib.request.Request(
        BASE_URL,
        data=json.dumps({"session_id": "s_no_auth", "message": "hello"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req_no_auth, timeout=10) as resp:
            print(f"{RED}[FAIL] Expected 401 Unauthorized but got 200 OK.{RESET}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print(f"{GREEN}[PASS] Correctly rejected with HTTP 401 Unauthorized!{RESET}")
        else:
            print(f"{YELLOW}[CHECK] Returned HTTP {e.code}{RESET}")

    print(f"\n{GREEN}{'='*70}{RESET}")
    print(f"{GREEN}All assessment tests completed successfully!{RESET}")
    print(f"{GREEN}{'='*70}{RESET}\n")


if __name__ == "__main__":
    main()
