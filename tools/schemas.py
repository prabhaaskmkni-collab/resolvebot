"""
tools/schemas.py — OpenAI-format JSON schemas for the 5 tools.
These are passed to the LLM so it knows when and how to call each tool.
"""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_orders",
            "description": (
                "Look up the customer's orders, items, and shipment details. "
                "Use this when the customer asks about order status, tracking, delivery, or shipment. "
                "Also returns computed values: days_since_delivery and warranty info per item. "
                "Pass order_id if the customer mentions a specific order."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The specific order ID (e.g. SS-10458). Omit to list all orders."
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by order status (processing, shipped, delivered, etc.)."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": (
                "Search the store's current policy documents for paragraphs that answer the customer's question. "
                "Use this for questions about returns, refunds, shipping fees, warranties, exchanges, cancellations, "
                "or any store policy. Returns matching sections with doc_id and section reference for citations. "
                "Only current, applicable policies are returned — never superseded ones."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The topic or question to search for in the policies."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_return_eligibility",
            "description": (
                "Check whether specific items in an order can be returned. "
                "Python code makes the decision — NOT the LLM. "
                "Use this before proposing a return, or when the customer asks 'can I return this?'. "
                "Returns 'eligible: true' or an error_code explaining why not."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID containing the items to return."
                    },
                    "item_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of item IDs to return (e.g. ['SS-10458-1'])."
                    },
                    "reason": {
                        "type": "string",
                        "enum": ["changed_mind", "defective"],
                        "description": "Reason for return: 'changed_mind' or 'defective' (includes damaged or wrong item)."
                    }
                },
                "required": ["order_id", "item_ids", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_return_request",
            "description": (
                "Create a return request and save it to the database. "
                "ONLY call this after the customer has explicitly said YES to a proposal. "
                "Never call this speculatively. The function re-checks eligibility before saving."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID."
                    },
                    "item_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Item IDs to include in the return."
                    },
                    "reason": {
                        "type": "string",
                        "enum": ["changed_mind", "defective"],
                        "description": "Reason for return."
                    }
                },
                "required": ["order_id", "item_ids", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_support_ticket",
            "description": (
                "Open a support ticket (warranty or cancellation) and save it to the database. "
                "ONLY call this after the customer has explicitly said YES to a proposal. "
                "Never call this speculatively. Eligibility is re-checked before saving."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID."
                    },
                    "ticket_type": {
                        "type": "string",
                        "enum": ["warranty", "cancellation"],
                        "description": "Type of support ticket."
                    },
                    "summary": {
                        "type": "string",
                        "description": "Short description of the issue or reason for the ticket."
                    }
                },
                "required": ["order_id", "ticket_type", "summary"]
            }
        }
    }
]
