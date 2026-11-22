"""SQLAlchemy ORM models for Customer Support Order Service.

Entities:
- Customer: Customer account profile.
- Order: Customer order with lifecycle status constraint.
- OrderItem: Line items associated with an order (quantity > 0 constraint).
- Shipment: Physical fulfillment tracking with supported status constraint.
- WarehouseEvent: Historical timeline tracking events with supported status constraint.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# Supported Order Lifecycle Statuses
VALID_ORDER_STATUSES = (
    "processing_in_warehouse",
    "packed",
    "shipped",
    "in_transit",
    "out_for_delivery",
    "delivered",
    "cancelled",
)

# Supported Shipment Statuses
VALID_SHIPMENT_STATUSES = (
    "created",
    "label_created",
    "picked_up",
    "shipped",
    "in_transit",
    "out_for_delivery",
    "delivered",
    "failed_delivery",
    "returned",
    "cancelled",
)

# Supported Warehouse and Tracking Event Statuses
VALID_WAREHOUSE_EVENT_STATUSES = (
    "order_received",
    "picked",
    "picked_and_packed",
    "label_created",
    "departed_sort_facility",
    "arrived_at_facility",
    "shipped",
    "in_transit",
    "out_for_delivery",
    "delivered",
    "failed_delivery",
    "returned",
    "exception",
)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    orders: Mapped[List["Order"]] = relationship(
        "Order", back_populates="customer", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Customer id={self.id} email='{self.email}'>"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            f"status IN {VALID_ORDER_STATUSES}",
            name="ck_orders_valid_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    customer: Mapped["Customer"] = relationship("Customer", back_populates="orders")
    items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    shipments: Mapped[List["Shipment"]] = relationship(
        "Shipment", back_populates="order", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Order id={self.id} order_number='{self.order_number}' status='{self.status}'>"


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="ck_order_items_quantity_positive",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationships
    order: Mapped["Order"] = relationship("Order", back_populates="items")

    def __repr__(self) -> str:
        return f"<OrderItem id={self.id} product='{self.product_name}' qty={self.quantity}>"


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        CheckConstraint(
            f"status IN {VALID_SHIPMENT_STATUSES}",
            name="ck_shipments_valid_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    carrier: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tracking_number: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="created")
    estimated_delivery: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    order: Mapped["Order"] = relationship("Order", back_populates="shipments")
    events: Mapped[List["WarehouseEvent"]] = relationship(
        "WarehouseEvent",
        back_populates="shipment",
        cascade="all, delete-orphan",
        order_by="WarehouseEvent.occurred_at.asc()",
    )

    def __repr__(self) -> str:
        return f"<Shipment id={self.id} carrier='{self.carrier}' tracking='{self.tracking_number}'>"


class WarehouseEvent(Base):
    __tablename__ = "warehouse_events"
    __table_args__ = (
        CheckConstraint(
            f"status IN {VALID_WAREHOUSE_EVENT_STATUSES}",
            name="ck_warehouse_events_valid_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    shipment: Mapped["Shipment"] = relationship("Shipment", back_populates="events")

    def __repr__(self) -> str:
        return f"<WarehouseEvent id={self.id} status='{self.status}' at={self.occurred_at}>"
