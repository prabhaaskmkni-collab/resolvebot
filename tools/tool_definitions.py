"""
tools/tool_definitions.py — The 5 tools as callable Python functions.
Tool names match exactly what the TASK PDF specifies (used in tests).
Customer ID is ALWAYS taken from the request context, NEVER from the LLM.
"""
import uuid
from datetime import datetime
from config import APP_TODAY_STR
from db.queries import (
    get_orders_for_customer, get_order_items, get_shipment,
    insert_return_request, insert_support_ticket,
)
from tools.business_rules import (
    check_return_eligibility, check_cancellation_eligibility,
    check_warranty_eligibility, days_since_delivery,
    warranty_end_date, is_warranty_active, APP_TODAY,
)
from policies.loader import get_policy_store


# ── Tool 1: get_orders ─────────────────────────────────────────────────────────

def get_orders(customer_id: str, order_id: str = None, status: str = None) -> dict:
    """
    Return customer's orders, their items and delivery details.
    Also computes: delivery date, days_since_delivery, warranty_end_date per item.
    SECURITY: customer_id comes from header, never from LLM.
    """
    orders = get_orders_for_customer(customer_id, order_id=order_id, status=status)
    if not orders:
        if order_id:
            return {"error_code": "ORDER_NOT_FOUND", "message": "I couldn't find that order on your account."}
        return {"orders": []}

    result = []
    for order in orders:
        oid = order["order_id"]
        items_raw = get_order_items(oid)
        shipment = get_shipment(oid)

        # Compute delivery info
        delivered_at = shipment["delivered_at"] if shipment else None
        days = days_since_delivery(delivered_at) if delivered_at else None

        # Enrich each item with warranty info
        items_enriched = []
        for item in items_raw:
            wc = item["warranty_class"]
            w_end = warranty_end_date(delivered_at, wc) if delivered_at else None
            w_active = is_warranty_active(delivered_at, wc) if delivered_at else False
            items_enriched.append({
                **item,
                "warranty_end_date": w_end.isoformat() if w_end else None,
                "warranty_active": w_active,
            })

        result.append({
            "order_id": oid,
            "order_date": order["order_date"],
            "status": order["status"],
            "subtotal": order["subtotal"],
            "shipping_fee": order["shipping_fee"],
            "total": order["total"],
            "payment_method": order["payment_method"],
            "shipment": {
                "carrier": shipment["carrier"] if shipment else None,
                "tracking_no": shipment["tracking_no"] if shipment else None,
                "status": shipment["status"] if shipment else None,
                "shipped_at": shipment["shipped_at"] if shipment else None,
                "delivered_at": delivered_at,
                "eta": shipment["eta"] if shipment else None,
                "original_eta": shipment["original_eta"] if shipment else None,
            } if shipment else None,
            "delivery_date": delivered_at[:10] if delivered_at else None,
            "days_since_delivery": days,
            "items": items_enriched,
        })

    return {"orders": result}


# ── Tool 2: search_policy ──────────────────────────────────────────────────────

def search_policy(query: str) -> dict:
    """
    Search current policy documents for paragraphs matching the query.
    Returns matching sections with doc_id and section reference.
    NEVER returns superseded documents.
    """
    store = get_policy_store()
    results = store.search(query, top_k=5)
    if not results:
        return {
            "found": False,
            "message": "No current policy covers this question.",
            "sections": [],
        }
    return {
        "found": True,
        "sections": results,
    }


# ── Tool 3: check_return_eligibility ──────────────────────────────────────────

def tool_check_return_eligibility(
    customer_id: str, order_id: str, item_ids: list[str], reason: str
) -> dict:
    """
    Check if items can be returned. All logic is in Python (business_rules.py).
    Returns 'eligible' or an error_code with message.
    """
    return check_return_eligibility(customer_id, order_id, item_ids, reason)


# ── Tool 4: create_return_request ─────────────────────────────────────────────

def create_return_request(
    customer_id: str, order_id: str, item_ids: list[str], reason: str
) -> dict:
    """
    Write a return request to the DB.
    SAFETY: Re-checks eligibility just before saving. Saves only if check passes.
    """
    eligibility = check_return_eligibility(customer_id, order_id, item_ids, reason)
    if not eligibility.get("eligible"):
        return {
            "status": "error",
            "error_code": eligibility.get("error_code", "INELIGIBLE"),
            "message": eligibility.get("message", "Return not eligible."),
        }

    request_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()
    insert_return_request(request_id, order_id, customer_id, item_ids, reason, created_at)
    return {
        "status": "success",
        "request_id": request_id,
        "order_id": order_id,
        "item_ids": item_ids,
        "reason": reason,
        "created_at": created_at,
        "message": f"Return request created (ID: {request_id}).",
    }


# ── Tool 5: create_support_ticket ────────────────────────────────────────────

def create_support_ticket(
    customer_id: str, order_id: str, ticket_type: str, summary: str
) -> dict:
    """
    Write a support ticket to the DB.
    ticket_type must be 'warranty' or 'cancellation'.
    SAFETY: Re-checks eligibility just before saving.
    """
    valid_types = ("warranty", "cancellation")
    if ticket_type not in valid_types:
        return {
            "status": "error",
            "error_code": "INVALID_TICKET_TYPE",
            "message": f"ticket_type must be one of {valid_types}.",
        }

    # Re-check eligibility before saving
    if ticket_type == "cancellation":
        eligibility = check_cancellation_eligibility(customer_id, order_id)
        if not eligibility.get("eligible"):
            return {
                "status": "error",
                "error_code": eligibility.get("error_code", "INELIGIBLE"),
                "message": eligibility.get("message"),
            }

    elif ticket_type == "warranty":
        eligibility = check_warranty_eligibility(customer_id, order_id)
        if not eligibility.get("eligible"):
            return {
                "status": "error",
                "error_code": eligibility.get("error_code", "INELIGIBLE"),
                "message": eligibility.get("message"),
            }

    ticket_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()
    insert_support_ticket(ticket_id, order_id, customer_id, ticket_type, summary, created_at)
    return {
        "status": "success",
        "ticket_id": ticket_id,
        "order_id": order_id,
        "ticket_type": ticket_type,
        "created_at": created_at,
        "message": f"Support ticket created (ID: {ticket_id}, type: {ticket_type}).",
    }
