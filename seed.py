"""Idempotent seed data for Customer Support Order Service.

Populates customers, orders, order items, shipments, and warehouse events
for test orders:
- 10432: Out for delivery (FedEx)
- 5012: Processing in warehouse (USPS)
- 8821: Delivered (UPS)

Designed for idempotent execution: running multiple times does not create duplicates.
Database schema should be initialized via Alembic migrations.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import engine, get_db
from models import Customer, Order, OrderItem, Shipment, WarehouseEvent


def seed_database(session: Session = None, target_engine=None) -> None:
    """Seed the database with sample customer and order records idempotently."""

    def _seed(db: Session):
        now = datetime.now(timezone.utc)

        # 1. Seed Customers
        customers_data = [
            {"email": "alice.smith@example.com", "name": "Alice Smith"},
            {"email": "bob.jones@example.com", "name": "Bob Jones"},
            {"email": "carol.white@example.com", "name": "Carol White"},
        ]
        customers = {}
        for c_data in customers_data:
            cust = db.scalar(select(Customer).where(Customer.email == c_data["email"]))
            if not cust:
                cust = Customer(name=c_data["name"], email=c_data["email"])
                db.add(cust)
                db.flush()
            customers[c_data["email"]] = cust

        # 2. Seed Order 10432 (Out for Delivery - FedEx)
        if not db.scalar(select(Order).where(Order.order_number == "10432")):
            order_10432 = Order(
                order_number="10432",
                customer=customers["alice.smith@example.com"],
                status="out_for_delivery",
                created_at=now - timedelta(days=2),
            )
            db.add(order_10432)
            db.flush()

            db.add(OrderItem(order=order_10432, product_name="Ergonomic Mechanical Keyboard", quantity=1))

            shipment_10432 = Shipment(
                order=order_10432,
                carrier="FedEx",
                tracking_number="FX-998231",
                status="out_for_delivery",
                estimated_delivery=now + timedelta(hours=4),
                created_at=now - timedelta(days=1, hours=12),
            )
            db.add(shipment_10432)
            db.flush()

            db.add_all([
                WarehouseEvent(
                    shipment=shipment_10432,
                    status="picked_and_packed",
                    location="Warehouse A (Louisville, KY)",
                    description="Package picked, packed, and assigned to FedEx carrier",
                    occurred_at=now - timedelta(days=1, hours=10),
                ),
                WarehouseEvent(
                    shipment=shipment_10432,
                    status="departed_sort_facility",
                    location="Louisville Hub, KY",
                    description="Departed carrier sorting facility",
                    occurred_at=now - timedelta(hours=18),
                ),
                WarehouseEvent(
                    shipment=shipment_10432,
                    status="out_for_delivery",
                    location="Local Delivery Station",
                    description="Package is on vehicle out for delivery today",
                    occurred_at=now - timedelta(hours=3),
                ),
            ])

        # 3. Seed Order 5012 (Processing in Warehouse - USPS Label Created)
        if not db.scalar(select(Order).where(Order.order_number == "5012")):
            order_5012 = Order(
                order_number="5012",
                customer=customers["bob.jones@example.com"],
                status="processing_in_warehouse",
                created_at=now - timedelta(days=1),
            )
            db.add(order_5012)
            db.flush()

            db.add(OrderItem(order=order_5012, product_name="USB-C Charging Hub", quantity=1))

            shipment_5012 = Shipment(
                order=order_5012,
                carrier="USPS",
                tracking_number="US-441029",
                status="label_created",
                estimated_delivery=now + timedelta(days=2),
                created_at=now - timedelta(hours=4),
            )
            db.add(shipment_5012)
            db.flush()

            db.add_all([
                WarehouseEvent(
                    shipment=shipment_5012,
                    status="order_received",
                    location="Fulfillment Center B (Dallas, TX)",
                    description="Order received into warehouse fulfillment queue",
                    occurred_at=now - timedelta(days=1),
                ),
                WarehouseEvent(
                    shipment=shipment_5012,
                    status="label_created",
                    location="Fulfillment Center B (Dallas, TX)",
                    description="Shipping label created, package awaiting pickup by carrier",
                    occurred_at=now - timedelta(hours=3),
                ),
            ])

        # 4. Seed Order 8821 (Delivered - UPS)
        if not db.scalar(select(Order).where(Order.order_number == "8821")):
            order_8821 = Order(
                order_number="8821",
                customer=customers["carol.white@example.com"],
                status="delivered",
                created_at=now - timedelta(days=4),
            )
            db.add(order_8821)
            db.flush()

            db.add(OrderItem(order=order_8821, product_name="Noise Cancelling Headphones", quantity=1))

            shipment_8821 = Shipment(
                order=order_8821,
                carrier="UPS",
                tracking_number="1Z-999AA1",
                status="delivered",
                estimated_delivery=now - timedelta(days=1),
                created_at=now - timedelta(days=3),
            )
            db.add(shipment_8821)
            db.flush()

            db.add_all([
                WarehouseEvent(
                    shipment=shipment_8821,
                    status="shipped",
                    location="UPS Gateway (Atlanta, GA)",
                    description="Departed facility",
                    occurred_at=now - timedelta(days=2),
                ),
                WarehouseEvent(
                    shipment=shipment_8821,
                    status="delivered",
                    location="Front Porch",
                    description="Delivered to front porch, signed by resident",
                    occurred_at=now - timedelta(days=1),
                ),
            ])

        db.commit()

    if session is not None:
        _seed(session)
    else:
        with get_db() as db_session:
            _seed(db_session)


if __name__ == "__main__":
    print("Seeding database...")
    seed_database()
    print("Database seeding completed successfully.")
