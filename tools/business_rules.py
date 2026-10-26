"""
tools/business_rules.py — All eligibility logic written in Python.
The LLM NEVER makes decisions; it only explains these results.
All numbers come from policy_parameters in the DB, never hardcoded.
"""
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from db.queries import get_policy_parameters, get_orders_for_customer, get_order_items, get_shipment
from config import APP_TODAY_STR

APP_TODAY: date = date.fromisoformat(APP_TODAY_STR)

# ── Load policy parameters once ───────────────────────────────────────────────
_params: dict | None = None

def _get_params() -> dict:
    global _params
    if _params is None:
        _params = get_policy_parameters()
    return _params


def get_return_window_days() -> int:
    return int(_get_params().get("return_window_days", 30))


def get_standard_warranty_months() -> int:
    return int(_get_params().get("standard_warranty_months", 12))


def get_extended_warranty_months() -> int:
    return int(_get_params().get("extended_warranty_months", 24))


# ── Date helpers ──────────────────────────────────────────────────────────────

def days_since_delivery(delivered_at: str) -> int:
    """
    Days from delivery date to APP_TODAY.
    delivered_at is ISO datetime string e.g. '2026-06-11T19:27:00'.
    Day 0 = delivery date. Day 30 = 30 days later (still allowed).
    """
    delivery_date = date.fromisoformat(delivered_at[:10])
    return (APP_TODAY - delivery_date).days


def warranty_end_date(delivered_at: str, warranty_class: str) -> date | None:
    """
    Compute warranty end date using relativedelta for correct month arithmetic.
    Returns None if no warranty.
    """
    if warranty_class == "none":
        return None
    delivery_date = date.fromisoformat(delivered_at[:10])
    params = _get_params()
    if warranty_class == "extended":
        months = int(params.get("extended_warranty_months", 24))
    else:  # standard
        months = int(params.get("standard_warranty_months", 12))
    return delivery_date + relativedelta(months=months)


def is_warranty_active(delivered_at: str, warranty_class: str) -> bool:
    """True if APP_TODAY is on or before the warranty end date."""
    end = warranty_end_date(delivered_at, warranty_class)
    if end is None:
        return False
    return APP_TODAY <= end


# ── Return eligibility ────────────────────────────────────────────────────────

def check_return_eligibility(
    customer_id: str,
    order_id: str,
    item_ids: list[str],
    reason: str,
) -> dict:
    """
    Full eligibility check as specified in TASK §2.3.
    Returns {"eligible": True} or {"eligible": False, "error_code": "...", "message": "..."}
    """
    # Validate reason
    if reason not in ("changed_mind", "defective"):
        return {
            "eligible": False,
            "error_code": "INVALID_REASON",
            "message": "Reason must be 'changed_mind' or 'defective'.",
        }

    # Check 1: Order exists and belongs to customer
    orders = get_orders_for_customer(customer_id, order_id=order_id)
    if not orders:
        return {
            "eligible": False,
            "error_code": "ORDER_NOT_FOUND",
            "message": "I couldn't find that order on your account.",
        }
    order = orders[0]

    # Check 1b: Order has been delivered
    shipment = get_shipment(order_id)
    if not shipment or not shipment.get("delivered_at"):
        return {
            "eligible": False,
            "error_code": "NOT_DELIVERED",
            "message": "This order has not been delivered yet.",
        }

    # Validate item_ids exist in this order
    all_items = get_order_items(order_id)
    items_by_id = {item["item_id"]: item for item in all_items}
    for iid in item_ids:
        if iid not in items_by_id:
            return {
                "eligible": False,
                "error_code": "INVALID_ITEM",
                "message": f"Item {iid} is not in this order.",
            }

    # Check for each item in order
    for iid in item_ids:
        item = items_by_id[iid]

        # Check 2: Product returnable
        returnable = item["returnable"]
        if returnable == "no":
            return {
                "eligible": False,
                "error_code": "NON_RETURNABLE",
                "message": f"'{item['product_name']}' cannot be returned (gift cards and software are never returnable).",
            }

        # Check 3: Within return window
        days = days_since_delivery(shipment["delivered_at"])
        window = get_return_window_days()
        if days > window:
            return {
                "eligible": False,
                "error_code": "RETURN_WINDOW_EXPIRED",
                "message": f"The return window ({window} days) has expired. It has been {days} days since delivery.",
            }

        # Check 4: Opened + changed_mind + sealed-only product
        if reason == "changed_mind" and item["opened"] and returnable == "unopened_only":
            return {
                "eligible": False,
                "error_code": "OPENED_NOT_RETURNABLE",
                "message": f"'{item['product_name']}' can only be returned if the hygiene seal is unbroken. Once opened, it cannot be returned for a change of mind.",
            }

    # All checks passed
    days = days_since_delivery(shipment["delivered_at"])
    window = get_return_window_days()
    return {
        "eligible": True,
        "days_since_delivery": days,
        "return_window_days": window,
        "days_remaining": window - days,
    }


# ── Cancellation eligibility ──────────────────────────────────────────────────

def check_cancellation_eligibility(customer_id: str, order_id: str) -> dict:
    """Check if an order can be cancelled (must be in 'processing' status)."""
    orders = get_orders_for_customer(customer_id, order_id=order_id)
    if not orders:
        return {
            "eligible": False,
            "error_code": "ORDER_NOT_FOUND",
            "message": "I couldn't find that order on your account.",
        }
    order = orders[0]
    if order["status"] != "processing":
        return {
            "eligible": False,
            "error_code": "ORDER_ALREADY_SHIPPED",
            "message": "This order has already been shipped and cannot be cancelled. You can return it after delivery.",
        }
    return {"eligible": True}


# ── Warranty eligibility ──────────────────────────────────────────────────────

def check_warranty_eligibility(customer_id: str, order_id: str) -> dict:
    """Check if at least one item in an order is still under warranty."""
    orders = get_orders_for_customer(customer_id, order_id=order_id)
    if not orders:
        return {
            "eligible": False,
            "error_code": "ORDER_NOT_FOUND",
            "message": "I couldn't find that order on your account.",
        }

    shipment = get_shipment(order_id)
    if not shipment or not shipment.get("delivered_at"):
        return {
            "eligible": False,
            "error_code": "NOT_DELIVERED",
            "message": "This order has not been delivered yet.",
        }

    all_items = get_order_items(order_id)
    active_items = []
    for item in all_items:
        wc = item["warranty_class"]
        if wc == "none":
            continue
        end = warranty_end_date(shipment["delivered_at"], wc)
        active = is_warranty_active(shipment["delivered_at"], wc)
        if active:
            active_items.append({
                "item_id": item["item_id"],
                "product_name": item["product_name"],
                "warranty_class": wc,
                "warranty_end_date": end.isoformat() if end else None,
            })

    if not active_items:
        return {
            "eligible": False,
            "error_code": "WARRANTY_EXPIRED",
            "message": "No items in this order are currently under warranty.",
        }
    return {"eligible": True, "covered_items": active_items}
