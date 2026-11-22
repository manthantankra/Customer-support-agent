"""Comprehensive Test Suite for Order Lookup Service and Database Integration.

Covers all 13 test requirements specified in Section 10:
1. Order 10432 found out-for-delivery lifecycle.
2. Order 5012 found processing in warehouse.
3. Order 8821 found delivered.
4. Order 9999 returns structured not-found response.
5. Order with no shipment returns valid order data without crashing.
6. Order with missing tracking information handled correctly.
7. Order with multiple shipments returns all relevant shipments.
8. Tracking history returned in chronological order.
9. Missing order ID handled as validation error.
10. Empty order ID handled as validation error.
11. Malformed/unexpected data handled gracefully.
12. Database unavailability handled separately from order not found.
13. Database sessions and transactions cleaned up correctly.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from models import Base, Customer, Order, OrderItem, Shipment, WarehouseEvent
from order_service import get_order_by_number, validate_order_id
from seed import seed_database


class TestOrderServiceIsolated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use isolated in-memory SQLite database for deterministic test execution
        cls.test_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        cls.TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.test_engine)
        Base.metadata.create_all(bind=cls.test_engine)

        # Seed standard sample records
        with cls.TestSessionLocal() as session:
            seed_database(session)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=cls.test_engine)
        cls.test_engine.dispose()

    def setUp(self):
        self.session: Session = self.TestSessionLocal()

    def tearDown(self):
        self.session.close()

    # 1. Order 10432 is found and has an out-for-delivery lifecycle
    def test_01_order_10432_out_for_delivery(self):
        res = get_order_by_number("10432", session=self.session)
        self.assertTrue(res["success"])
        self.assertTrue(res["found"])
        self.assertIsNone(res["error"])
        data = res["data"]
        self.assertEqual(data["order_id"], "10432")
        self.assertEqual(data["status"], "out_for_delivery")
        self.assertIn("Ergonomic Mechanical Keyboard", data["items"])
        self.assertGreater(len(data["shipments"]), 0)
        self.assertEqual(data["shipments"][0]["carrier"], "FedEx")
        self.assertEqual(data["shipments"][0]["tracking_number"], "FX-998231")

    # 2. Order 5012 is found and is processing in the warehouse
    def test_02_order_5012_processing_in_warehouse(self):
        res = get_order_by_number("5012", session=self.session)
        self.assertTrue(res["success"])
        self.assertTrue(res["found"])
        data = res["data"]
        self.assertEqual(data["order_id"], "5012")
        self.assertEqual(data["status"], "processing_in_warehouse")
        self.assertIn("USB-C Charging Hub", data["items"])
        self.assertEqual(data["shipments"][0]["carrier"], "USPS")

    # 3. Order 8821 is found and is delivered
    def test_03_order_8821_delivered(self):
        res = get_order_by_number("8821", session=self.session)
        self.assertTrue(res["success"])
        self.assertTrue(res["found"])
        data = res["data"]
        self.assertEqual(data["order_id"], "8821")
        self.assertEqual(data["status"], "delivered")
        self.assertEqual(data["shipments"][0]["carrier"], "UPS")
        self.assertEqual(data["shipments"][0]["status"], "delivered")

    # 4. Order 9999 returns a structured not-found response
    def test_04_order_9999_not_found(self):
        res = get_order_by_number("9999", session=self.session)
        self.assertTrue(res["success"])
        self.assertFalse(res["found"])
        self.assertIsNone(res["data"])
        self.assertIsNotNone(res["error"])
        self.assertEqual(res["error"]["code"], "ORDER_NOT_FOUND")
        self.assertIn("9999", res["error"]["message"])

    # 5. An order with no shipment returns valid order data without crashing
    def test_05_order_with_no_shipment(self):
        customer = self.session.query(Customer).first()
        order_no_ship = Order(
            order_number="ORDER-NO-SHIP",
            customer=customer,
            status="packed",
        )
        self.session.add(order_no_ship)
        self.session.flush()
        self.session.add(OrderItem(order=order_no_ship, product_name="Test Product", quantity=1))
        self.session.commit()

        res = get_order_by_number("ORDER-NO-SHIP", session=self.session)
        self.assertTrue(res["success"])
        self.assertTrue(res["found"])
        self.assertEqual(res["data"]["shipments"], [])
        self.assertEqual(res["data"]["tracking_history"], [])
        self.assertEqual(res["data"]["items"], ["Test Product"])

    # 6. An order with missing tracking information is handled correctly
    def test_06_order_missing_tracking_info(self):
        customer = self.session.query(Customer).first()
        order_no_track = Order(
            order_number="ORDER-NO-TRACK",
            customer=customer,
            status="processing_in_warehouse",
        )
        self.session.add(order_no_track)
        self.session.flush()
        shipment_unassigned = Shipment(
            order=order_no_track,
            carrier=None,
            tracking_number=None,
            status="created",
            estimated_delivery=None,
        )
        self.session.add(shipment_unassigned)
        self.session.commit()

        res = get_order_by_number("ORDER-NO-TRACK", session=self.session)
        self.assertTrue(res["success"])
        self.assertTrue(res["found"])
        shipment_data = res["data"]["shipments"][0]
        self.assertIsNone(shipment_data["carrier"])
        self.assertIsNone(shipment_data["tracking_number"])
        self.assertIsNone(shipment_data["estimated_delivery"])

    # 7. An order with multiple shipments returns all relevant shipments
    def test_07_order_with_multiple_shipments(self):
        customer = self.session.query(Customer).first()
        multi_order = Order(
            order_number="ORDER-MULTI-SHIP",
            customer=customer,
            status="in_transit",
        )
        self.session.add(multi_order)
        self.session.flush()

        s1 = Shipment(order=multi_order, carrier="FedEx", tracking_number="FX-111", status="in_transit")
        s2 = Shipment(order=multi_order, carrier="UPS", tracking_number="1Z-222", status="delivered")
        self.session.add_all([s1, s2])
        self.session.commit()

        res = get_order_by_number("ORDER-MULTI-SHIP", session=self.session)
        self.assertTrue(res["success"])
        self.assertEqual(len(res["data"]["shipments"]), 2)
        carriers = [s["carrier"] for s in res["data"]["shipments"]]
        self.assertIn("FedEx", carriers)
        self.assertIn("UPS", carriers)

    # 8. Tracking history is returned in chronological order
    def test_08_tracking_history_chronological_order(self):
        customer = self.session.query(Customer).first()
        chron_order = Order(order_number="ORDER-CHRON", customer=customer, status="in_transit")
        self.session.add(chron_order)
        self.session.flush()

        shipment = Shipment(order=chron_order, carrier="DHL", tracking_number="DHL-999", status="in_transit")
        self.session.add(shipment)
        self.session.flush()

        now = datetime.now(timezone.utc)
        # Insert events out of order
        ev2 = WarehouseEvent(shipment=shipment, status="in_transit", occurred_at=now - timedelta(hours=5), location="Loc2")
        ev1 = WarehouseEvent(shipment=shipment, status="picked", occurred_at=now - timedelta(hours=10), location="Loc1")
        ev3 = WarehouseEvent(shipment=shipment, status="out_for_delivery", occurred_at=now - timedelta(hours=1), location="Loc3")
        self.session.add_all([ev2, ev1, ev3])
        self.session.commit()

        res = get_order_by_number("ORDER-CHRON", session=self.session)
        history = res["data"]["tracking_history"]
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["status"], "picked")
        self.assertEqual(history[1]["status"], "in_transit")
        self.assertEqual(history[2]["status"], "out_for_delivery")

    # 9. Missing order ID is handled as a validation error
    def test_09_missing_order_id_validation_error(self):
        res = get_order_by_number(None)
        self.assertFalse(res["success"])
        self.assertIsNone(res["found"])
        self.assertEqual(res["error"]["code"], "INVALID_INPUT")
        self.assertIn("missing", res["error"]["message"].lower())

    # 10. Empty order ID is handled as a validation error
    def test_10_empty_order_id_validation_error(self):
        for empty_val in ["", "   ", "\t\n"]:
            res = get_order_by_number(empty_val)
            self.assertFalse(res["success"])
            self.assertIsNone(res["found"])
            self.assertEqual(res["error"]["code"], "INVALID_INPUT")

    # 11. Malformed or excessively long order ID
    def test_11_malformed_or_excessive_order_id(self):
        long_id = "A" * 60
        res = get_order_by_number(long_id)
        self.assertFalse(res["success"])
        self.assertEqual(res["error"]["code"], "INVALID_INPUT")

    # 12. Database unavailability is handled separately from order not found
    def test_12_database_unavailability_handling(self):
        broken_session = MagicMock(spec=Session)
        broken_session.scalars.side_effect = OperationalError("connection refused", {}, Exception("DB down"))

        res = get_order_by_number("10432", session=broken_session)
        self.assertFalse(res["success"])
        self.assertIsNone(res["found"])
        self.assertIsNone(res["data"])
        self.assertEqual(res["error"]["code"], "ORDER_SERVICE_UNAVAILABLE")
        # Ensure credentials/stacktrace not exposed in user-facing message
        self.assertNotIn("connection refused", res["error"]["message"].lower())
        self.assertNotIn("operationalerror", res["error"]["message"].lower())

    # 13. Database sessions and transactions are cleaned up correctly
    def test_13_session_cleanup_and_no_leak(self):
        from database import get_db
        from sqlalchemy import text

        session_closed = False

        class TrackedSession:
            def __init__(self, real_session):
                self._real = real_session

            def close(self):
                nonlocal session_closed
                session_closed = True
                self._real.close()

            def rollback(self):
                self._real.rollback()

            def commit(self):
                self._real.commit()

            def execute(self, *args, **kwargs):
                return self._real.execute(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._real, name)

        def mock_factory():
            real = self.TestSessionLocal()
            return TrackedSession(real)

        with get_db(session_factory=mock_factory) as s:
            s.execute(text("SELECT 1"))

        self.assertTrue(session_closed, "Database session was not properly closed after context exit.")

    # 14. Database check constraints reject invalid data
    def test_14_check_constraints_enforced(self):
        from sqlalchemy.exc import IntegrityError
        cust = self.session.query(Customer).first()

        # Quantity must be > 0
        order1 = Order(order_number="CK-TEST-ORD1", customer=cust, status="packed")
        self.session.add(order1)
        self.session.flush()
        bad_item = OrderItem(order=order1, product_name="Bad Item", quantity=0)
        self.session.add(bad_item)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()

        # Shipment status constraint
        order2 = Order(order_number="CK-TEST-ORD2", customer=cust, status="packed")
        self.session.add(order2)
        self.session.flush()
        bad_ship = Shipment(order=order2, carrier="FedEx", status="flying_invalid")
        self.session.add(bad_ship)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()

        # Warehouse event status constraint
        order3 = Order(order_number="CK-TEST-ORD3", customer=cust, status="packed")
        self.session.add(order3)
        self.session.flush()
        good_ship = Shipment(order=order3, carrier="FedEx", status="created")
        self.session.add(good_ship)
        self.session.flush()

        bad_ev = WarehouseEvent(shipment=good_ship, status="lost_in_space", occurred_at=datetime.now(timezone.utc))
        self.session.add(bad_ev)
        with self.assertRaises(IntegrityError):
            self.session.flush()
        self.session.rollback()


if __name__ == "__main__":
    unittest.main(verbosity=2)
