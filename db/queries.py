"""
db/queries.py — All SQL query functions for ResolveBot.
Business logic (date math, eligibility) lives in tools/, not here.
"""
import sqlite3
from typing import Optional
from db.connection import get_connection


def get_policy_parameters() -> dict:
    """Load all policy_parameters into a dict {key: value}."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT key, value FROM policy_parameters").fetchall()
        return {row["key"]: row["value"] for row in rows}
    finally:
        conn.close()


def get_customer_by_id(customer_id: str) -> Optional[dict]:
    """Return customer row or None."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_orders_for_customer(customer_id: str, order_id: Optional[str] = None,
                             status: Optional[str] = None) -> list[dict]:
    """
    Return orders belonging to this customer.
    Optionally filter by order_id and/or status.
    """
    conn = get_connection()
    try:
        sql = "SELECT * FROM orders WHERE customer_id = ?"
        params: list = [customer_id]
        if order_id:
            sql += " AND order_id = ?"
            params.append(order_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY order_date DESC"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_order_items(order_id: str) -> list[dict]:
    """Return all items for an order, joined with product details."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT oi.*, p.name as product_name, p.brand, p.category,
                   p.returnable, p.warranty_class, p.price
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            WHERE oi.order_id = ?
            """,
            (order_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_shipment(order_id: str) -> Optional[dict]:
    """Return shipment row for an order, or None."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM shipments WHERE order_id = ?", (order_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def insert_return_request(request_id: str, order_id: str, customer_id: str,
                           item_ids: list[str], reason: str, created_at: str) -> None:
    """Insert a new row into return_requests."""
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO return_requests
              (request_id, order_id, customer_id, item_ids, reason, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'requested', ?)
            """,
            (request_id, order_id, customer_id, ",".join(item_ids), reason, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def insert_support_ticket(ticket_id: str, order_id: str, customer_id: str,
                           ticket_type: str, summary: str, created_at: str) -> None:
    """Insert a new row into support_tickets."""
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO support_tickets
              (ticket_id, order_id, customer_id, ticket_type, summary, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'open', ?)
            """,
            (ticket_id, order_id, customer_id, ticket_type, summary, created_at),
        )
        conn.commit()
    finally:
        conn.close()
