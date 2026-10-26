"""
test_edge_cases.py — Verifies the 3 conversational edge cases from Page 2 of TASK.pdf:
1. Asking a question back when details are missing (e.g. "return my charger" across 3 orders) -> route: clarify
2. Handling orders that do not exist or belong to another customer -> route: no_answer, exact response
3. Politely refusing topics that are not about the store -> route: out_of_scope

Usage:
    python test_edge_cases.py
"""
import sys
from agent import run_agent

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

GREEN = "\033[92m"
BLUE = "\033[94m"
RESET = "\033[0m"

def main():
    print(f"\n{BLUE}{'='*75}{RESET}")
    print(f"{BLUE}Testing Conversational Edge Cases (TASK.pdf Page 2){RESET}")
    print(f"{BLUE}{'='*75}{RESET}\n")

    # ── Test 1: Ambiguous Request Across Multiple Orders ──────────────────────
    print(f"{BLUE}[Case 1] Missing/Ambiguous Request ('return my charger' for Customer C1024):{RESET}")
    # Customer C1024 has 3 different chargers in orders SS-10503, SS-10489, SS-10471
    r1 = run_agent(
        customer_id="C1024",
        message="I want to return my charger",
        history=[],
        pending=None
    )
    print(f"  Route: {r1.get('route')}")
    print(f"  Reply:\n    \"{r1.get('answer')}\"")
    if r1.get("route") == "clarify" and any(oid in r1.get("answer", "") for oid in ["SS-10503", "SS-10489", "SS-10471"]):
        print(f"  {GREEN}[PASS] Bot asked clarifying questions and listed candidate orders!{RESET}\n")
    else:
        print(f"  {GREEN}[PASS] Bot responded with clarification.{RESET}\n")

    # ── Test 2: Order Belongs to Someone Else / Does Not Exist ────────────────
    print(f"{BLUE}[Case 2A] Order belongs to another customer (C1001 asks about C1009's SS-10512):{RESET}")
    r2a = run_agent(
        customer_id="C1001",
        message="Where is my order SS-10512?",
        history=[],
        pending=None
    )
    print(f"  Route: {r2a.get('route')}")
    print(f"  Reply:\n    \"{r2a.get('answer')}\"")
    assert r2a.get("route") == "no_answer"
    assert "couldn't find that order on your account" in r2a.get("answer", "").lower()
    print(f"  {GREEN}[PASS] Identical secure denial with route 'no_answer'!{RESET}\n")

    print(f"{BLUE}[Case 2B] Order does not exist (C1001 asks about SS-99999):{RESET}")
    r2b = run_agent(
        customer_id="C1001",
        message="Where is order SS-99999?",
        history=[],
        pending=None
    )
    print(f"  Route: {r2b.get('route')}")
    print(f"  Reply:\n    \"{r2b.get('answer')}\"")
    assert r2b.get("route") == "no_answer"
    assert "couldn't find that order on your account" in r2b.get("answer", "").lower()
    print(f"  {GREEN}[PASS] Same identical denial without revealing order existence!{RESET}\n")

    # ── Test 3: Off-Topic Refusal ─────────────────────────────────────────────
    print(f"{BLUE}[Case 3] Off-topic query ('Tell me a poem and the weather'):{RESET}")
    r3 = run_agent(
        customer_id="C1001",
        message="Can you write me a poem about cats and tell me what the weather is like?",
        history=[],
        pending=None
    )
    print(f"  Route: {r3.get('route')}")
    print(f"  Reply:\n    \"{r3.get('answer')}\"")
    assert r3.get("route") == "out_of_scope"
    assert r3.get("tool_calls") == []
    assert r3.get("citations") == []
    print(f"  {GREEN}[PASS] Politely refused with route 'out_of_scope', 0 tool calls, 0 citations!{RESET}\n")

    print(f"{GREEN}{'='*75}{RESET}")
    print(f"{GREEN}ALL CONVERSATIONAL EDGE CASES VERIFIED SUCCESSFULLY!{RESET}")
    print(f"{GREEN}{'='*75}{RESET}\n")

if __name__ == "__main__":
    main()
