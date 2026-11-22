"""PostgreSQL Integration Test Suite for Customer Support Order Service.

Verifies:
1. Alembic migrations execute successfully against PostgreSQL.
2. Seed data is inserted correctly.
3. Re-running the seed script does not create duplicate records (idempotency).
4. Foreign-key relationships work correctly and reject invalid parent references.
5. Database constraints reject invalid data:
   - Order items quantity > 0
   - Orders status check constraint
   - Shipments status check constraint
   - Warehouse events status check constraint
6. An order can contain multiple items.
7. An order can contain multiple shipments.
8. Warehouse events are associated with the correct shipment in chronological order.
9. Order lookup returns expected structured response.
10. Missing orders return correct not-found response.
11. Database connection or query failures are handled correctly.

Configuration:
Reads TEST_DATABASE_URL from environment (default: postgresql+psycopg2://postgres:postgres@localhost:5432/support_test_db).
"""
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from dotenv import load_dotenv

load_dotenv()

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.config import Config
from models import Base, Customer, Order, OrderItem, Shipment, WarehouseEvent
from order_service import get_order_by_number
from seed import seed_database

DEFAULT_TEST_POSTGRES_URL = "postgresql+psycopg2://postgres:admin1234@localhost:5432/support_test_db"


def get_test_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_POSTGRES_URL)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def is_postgres_available(url: str) -> bool:
    """Check if the target PostgreSQL server is accessible."""
    try:
        admin_url = re.sub(r"/([^/]+)$", "/postgres", url)
        engine = create_engine(admin_url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


TEST_DB_URL = get_test_db_url()
POSTGRES_AVAILABLE = is_postgres_available(TEST_DB_URL)


@unittest.skipUnless(
    POSTGRES_AVAILABLE,
    f"PostgreSQL test instance is not reachable at {TEST_DB_URL}. "
    "Start postgres (e.g. docker compose up -d postgres) and set TEST_DATABASE_URL to run integration tests.",
)
class TestPostgresIntegration(unittest.TestCase):
    test_engine = None
    TestSession = None

    @classmethod
    def setUpClass(cls):
        admin_url = re.sub(r"/([^/]+)$", "/postgres", TEST_DB_URL)
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

        # Create isolated test database if it does not exist (or drop/recreate for a clean run)
        test_db_name = TEST_DB_URL.split("/")[-1].split("?")[0]
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text(f"SELECT 1 FROM pg_database WHERE datname = '{test_db_name}'")
            ).scalar()
            if exists:
                conn.execute(
                    text(
                        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        f"WHERE datname = '{test_db_name}' AND pid <> pg_backend_pid()"
                    )
                )
                conn.execute(text(f"DROP DATABASE {test_db_name}"))
            conn.execute(text(f"CREATE DATABASE {test_db_name}"))
        admin_engine.dispose()

        # Connect to the isolated test database
        cls.test_engine = create_engine(
            TEST_DB_URL,
            pool_pre_ping=True,
            isolation_level="READ COMMITTED",
        )
        cls.TestSession = sessionmaker(autocommit=False, autoflush=False, bind=cls.test_engine)

        # 1. Apply Alembic migrations from clean state
        alembic_ini_path = str(PROJECT_ROOT / "alembic.ini")
        alembic_cfg = Config(alembic_ini_path)
        alembic_cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
        command.upgrade(alembic_cfg, "head")

        # 2. Seed database records
        with cls.TestSession() as session:
            seed_database(session)

    @classmethod
    def tearDownClass(cls):
        if cls.test_engine:
            cls.test_engine.dispose()

    def setUp(self):
        self.session: Session = self.TestSession()

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    # Requirement 1: Alembic migrations applied successfully
    def test_01_alembic_migrations_applied(self):
        with self.test_engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            self.assertEqual(version, "002_add_missing_constraints")

    # Requirement 2 & 3: Seed data inserted correctly and idempotent
    def test_02_seed_data_and_idempotency(self):
        # Count records before second seed
        order_count_1 = self.session.scalar(select(text("count(*)")).select_from(Order))
        self.assertEqual(order_count_1, 3)

        # Execute seed a second time to verify idempotency
        seed_database(self.session)
        order_count_2 = self.session.scalar(select(text("count(*)")).select_from(Order))
        self.assertEqual(order_count_1, order_count_2, "Seeding created duplicate order records!")

    # Requirement 4: Foreign-key relationships work correctly
    def test_03_foreign_key_constraints(self):
        # Order with invalid customer_id must fail
        invalid_order = Order(
            order_number="INVALID-CUST-ORDER",
            customer_id=9999999,
            status="packed",
        )
        self.session.add(invalid_order)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()

        # OrderItem with invalid order_id must fail
        invalid_item = OrderItem(order_id=9999999, product_name="Phantom Item", quantity=1)
        self.session.add(invalid_item)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()

    # Requirement 5: Database constraints reject invalid data
    def test_04_check_constraints_enforced(self):
        cust = self.session.scalar(select(Customer).limit(1))
        self.assertIsNotNone(cust)

        # 1. Invalid order status
        bad_order = Order(order_number="BAD-STATUS-ORD", customer_id=cust.id, status="flying_in_sky")
        self.session.add(bad_order)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()

        # 2. Invalid item quantity (quantity <= 0)
        valid_order = Order(order_number="VALID-ORD-QTY", customer_id=cust.id, status="packed")
        self.session.add(valid_order)
        self.session.flush()

        bad_item = OrderItem(order_id=valid_order.id, product_name="Item", quantity=0)
        self.session.add(bad_item)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()

        # 3. Invalid shipment status
        valid_order2 = Order(order_number="VALID-ORD-SHIP", customer_id=cust.id, status="packed")
        self.session.add(valid_order2)
        self.session.flush()

        bad_shipment = Shipment(order_id=valid_order2.id, carrier="DHL", status="lost_at_sea")
        self.session.add(bad_shipment)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()

        # 4. Invalid warehouse event status
        valid_order3 = Order(order_number="VALID-ORD-EVENT", customer_id=cust.id, status="shipped")
        self.session.add(valid_order3)
        self.session.flush()

        valid_shipment = Shipment(order_id=valid_order3.id, carrier="DHL", status="shipped")
        self.session.add(valid_shipment)
        self.session.flush()

        bad_event = WarehouseEvent(
            shipment_id=valid_shipment.id,
            status="magically_disappeared",
            occurred_at=datetime.now(timezone.utc),
        )
        self.session.add(bad_event)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()

    # Requirement 6: Order can contain multiple items
    def test_05_order_multiple_items(self):
        cust = self.session.scalar(select(Customer).limit(1))
        order = Order(order_number="MULTI-ITEM-PG", customer_id=cust.id, status="packed")
        self.session.add(order)
        self.session.flush()

        self.session.add_all([
            OrderItem(order_id=order.id, product_name="Item Alpha", quantity=1),
            OrderItem(order_id=order.id, product_name="Item Beta", quantity=2),
            OrderItem(order_id=order.id, product_name="Item Gamma", quantity=3),
        ])
        self.session.commit()

        res = get_order_by_number("MULTI-ITEM-PG", session=self.session)
        self.assertTrue(res["success"])
        self.assertEqual(len(res["data"]["items"]), 3)
        self.assertIn("Item Alpha", res["data"]["items"])
        self.assertIn("Item Beta", res["data"]["items"])

    # Requirement 7: Order can contain multiple shipments
    def test_06_order_multiple_shipments(self):
        cust = self.session.scalar(select(Customer).limit(1))
        order = Order(order_number="MULTI-SHIP-PG", customer_id=cust.id, status="in_transit")
        self.session.add(order)
        self.session.flush()

        self.session.add_all([
            Shipment(order_id=order.id, carrier="FedEx", tracking_number="FX-PART1", status="in_transit"),
            Shipment(order_id=order.id, carrier="USPS", tracking_number="US-PART2", status="out_for_delivery"),
        ])
        self.session.commit()

        res = get_order_by_number("MULTI-SHIP-PG", session=self.session)
        self.assertTrue(res["success"])
        self.assertEqual(len(res["data"]["shipments"]), 2)
        carriers = [s["carrier"] for s in res["data"]["shipments"]]
        self.assertIn("FedEx", carriers)
        self.assertIn("USPS", carriers)

    # Requirement 8: Warehouse events associated with correct shipment in chronological order
    def test_07_warehouse_events_chronological(self):
        cust = self.session.scalar(select(Customer).limit(1))
        order = Order(order_number="EVENTS-ORD-PG", customer_id=cust.id, status="shipped")
        self.session.add(order)
        self.session.flush()

        ship = Shipment(order_id=order.id, carrier="UPS", tracking_number="1Z-CHRON", status="shipped")
        self.session.add(ship)
        self.session.flush()

        now = datetime.now(timezone.utc)
        # Add events in reverse order
        e3 = WarehouseEvent(shipment_id=ship.id, status="out_for_delivery", occurred_at=now - timedelta(hours=1))
        e1 = WarehouseEvent(shipment_id=ship.id, status="order_received", occurred_at=now - timedelta(hours=24))
        e2 = WarehouseEvent(shipment_id=ship.id, status="departed_sort_facility", occurred_at=now - timedelta(hours=12))
        self.session.add_all([e3, e1, e2])
        self.session.commit()

        res = get_order_by_number("EVENTS-ORD-PG", session=self.session)
        history = res["data"]["tracking_history"]
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["status"], "order_received")
        self.assertEqual(history[1]["status"], "departed_sort_facility")
        self.assertEqual(history[2]["status"], "out_for_delivery")

    # Requirement 9: Order lookup returns expected structured response
    def test_08_order_lookup_success_contract(self):
        res = get_order_by_number("10432", session=self.session)
        self.assertTrue(res["success"])
        self.assertTrue(res["found"])
        self.assertIsNone(res["error"])
        data = res["data"]
        self.assertEqual(data["order_id"], "10432")
        self.assertEqual(data["status"], "out_for_delivery")
        self.assertIn("Ergonomic Mechanical Keyboard", data["items"])
        self.assertEqual(data["shipments"][0]["carrier"], "FedEx")
        self.assertEqual(data["shipments"][0]["tracking_number"], "FX-998231")

    # Requirement 10: Missing order returns correct not-found response
    def test_09_order_not_found_contract(self):
        res = get_order_by_number("9999", session=self.session)
        self.assertTrue(res["success"])
        self.assertFalse(res["found"])
        self.assertIsNone(res["data"])
        self.assertEqual(res["error"]["code"], "ORDER_NOT_FOUND")

    # Requirement 11: Database failure handling
    def test_10_database_failure_handling(self):
        # Connect with broken engine
        broken_engine = create_engine("postgresql+psycopg2://bad_user:bad_pass@localhost:5432/bad_db")
        BrokenSession = sessionmaker(bind=broken_engine)

        with BrokenSession() as broken_session:
            res = get_order_by_number("10432", session=broken_session)
            self.assertFalse(res["success"])
            self.assertIsNone(res["found"])
            self.assertIsNone(res["data"])
            self.assertEqual(res["error"]["code"], "ORDER_SERVICE_UNAVAILABLE")
            # Raw credentials must NOT leak
            self.assertNotIn("bad_pass", res["error"]["message"])
            self.assertNotIn("bad_user", res["error"]["message"])
        broken_engine.dispose()


if __name__ == "__main__":
    unittest.main(verbosity=2)
