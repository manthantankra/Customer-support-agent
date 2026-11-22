"""Order Service Data Access Layer for Customer Support Agent.

Encapsulates all database interactions for orders, shipments, and tracking events.
Enforces the structured tool contract and isolates LangGraph from PostgreSQL details.
"""
import logging
import os
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from database import SessionLocal, get_db
from models import Order, WarehouseEvent

logger = logging.getLogger("order_service")


def validate_order_id(order_id_input: Any) -> Optional[str]:
    """Validate order ID input. Returns cleaned order_id or raises ValueError."""
    if order_id_input is None:
        raise ValueError("Order ID is missing.")

    order_id_str = str(order_id_input).strip()
    if not order_id_str:
        raise ValueError("Order ID cannot be empty or whitespace only.")

    if len(order_id_str) > 50:
        raise ValueError("Order ID exceeds maximum allowed length of 50 characters.")

    if len(order_id_str) < 2 or order_id_str.lower() in ("unknown", "null", "none"):
        raise ValueError("Invalid order ID format. Please provide a valid order identifier.")

    return order_id_str


def get_order_by_number(order_id_input: Any, session: Optional[Session] = None) -> Dict[str, Any]:
    """Retrieve order, shipment, and event details by business order number.

    Returns the agreed structured contract:
    - Success Found: {"tool": "order_lookup", "success": True, "found": True, "data": {...}, "error": None}
    - Success Not Found: {"tool": "order_lookup", "success": True, "found": False, "data": None, "error": {...}}
    - Invalid Input: {"tool": "order_lookup", "success": False, "found": None, "data": None, "error": {...}}
    - Service Error: {"tool": "order_lookup", "success": False, "found": None, "data": None, "error": {...}}
    """
    # 1. Input Validation
    try:
        clean_order_id = validate_order_id(order_id_input)
    except ValueError as val_err:
        return {
            "tool": "order_lookup",
            "success": False,
            "found": None,
            "data": None,
            "error": {
                "code": "INVALID_INPUT",
                "message": str(val_err),
            },
        }

    # 2. Database Execution
    def _execute_query(db: Session) -> Dict[str, Any]:
        stmt = (
            select(Order)
            .where(Order.order_number == clean_order_id)
            .options(
                selectinload(Order.items),
                selectinload(Order.shipments).selectinload(models_shipment_events),
            )
        )
        order = db.scalars(stmt).first()

        if not order:
            return {
                "tool": "order_lookup",
                "success": True,
                "found": False,
                "order_id": clean_order_id,
                "data": None,
                "error": {
                    "code": "ORDER_NOT_FOUND",
                    "message": f"No order matching order number '{clean_order_id}' was found.",
                },
            }

        # Format items safely
        items_list = [item.product_name for item in (order.items or [])]

        # Format shipments and chronological tracking history
        shipments_data = []
        all_events = []

        for shipment in order.shipments or []:
            shipments_data.append(
                {
                    "carrier": shipment.carrier,
                    "tracking_number": shipment.tracking_number,
                    "status": shipment.status,
                    "estimated_delivery": (
                        shipment.estimated_delivery.isoformat()
                        if shipment.estimated_delivery
                        else None
                    ),
                }
            )
            for event in shipment.events or []:
                all_events.append(event)

        # Sort all warehouse events chronologically
        all_events.sort(key=lambda ev: ev.occurred_at)
        tracking_history = [
            {
                "status": ev.status,
                "location": ev.location,
                "description": ev.description,
                "occurred_at": ev.occurred_at.isoformat() if ev.occurred_at else None,
            }
            for ev in all_events
        ]

        return {
            "tool": "order_lookup",
            "success": True,
            "found": True,
            "data": {
                "order_id": order.order_number,
                "status": order.status,
                "items": items_list,
                "shipments": shipments_data,
                "tracking_history": tracking_history,
            },
            "error": None,
        }

    # Internal helper for relationship loader
    from models import Shipment
    models_shipment_events = Shipment.events

    # Execute inside provided session or checkout one from connection pool
    try:
        if session is not None:
            return _execute_query(session)
        else:
            with get_db() as db:
                return _execute_query(db)
    except SQLAlchemyError as db_err:
        logger.error(
            "Database failure executing order lookup for order_id='%s': %s",
            clean_order_id,
            db_err,
            exc_info=True,
        )
        return {
            "tool": "order_lookup",
            "success": False,
            "found": None,
            "data": None,
            "error": {
                "code": "ORDER_SERVICE_UNAVAILABLE",
                "message": "Order information is temporarily unavailable. Please try again shortly.",
            },
        }
    except Exception as unexpected_err:
        logger.exception(
            "Unexpected error during order lookup for order_id='%s': %s",
            clean_order_id,
            unexpected_err,
        )
        # In development and test environments, re-raise programming errors so they are not hidden
        is_production = os.environ.get("ENV", "development").lower() in ("production", "prod")
        if not is_production:
            raise
        return {
            "tool": "order_lookup",
            "success": False,
            "found": None,
            "data": None,
            "error": {
                "code": "ORDER_SERVICE_UNAVAILABLE",
                "message": "Order information is temporarily unavailable. Please try again shortly.",
            },
        }
