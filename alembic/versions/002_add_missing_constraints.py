"""Add missing constraints on order_items, shipments, and warehouse_events.

Revision ID: 002_add_missing_constraints
Revises: 001_initial_order_schema
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '002_add_missing_constraints'
down_revision: Union[str, None] = '001_initial_order_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Check constraint on order_items: quantity must be greater than zero
    op.create_check_constraint(
        'ck_order_items_quantity_positive',
        'order_items',
        'quantity > 0'
    )

    # 2. Check constraint on shipments: status must be one of supported statuses
    op.create_check_constraint(
        'ck_shipments_valid_status',
        'shipments',
        "status IN ('created', 'label_created', 'picked_up', 'shipped', 'in_transit', 'out_for_delivery', 'delivered', 'failed_delivery', 'returned', 'cancelled')"
    )

    # 3. Check constraint on warehouse_events: status must be one of supported statuses
    op.create_check_constraint(
        'ck_warehouse_events_valid_status',
        'warehouse_events',
        "status IN ('order_received', 'picked', 'picked_and_packed', 'label_created', 'departed_sort_facility', 'arrived_at_facility', 'shipped', 'in_transit', 'out_for_delivery', 'delivered', 'failed_delivery', 'returned', 'exception')"
    )


def downgrade() -> None:
    op.drop_constraint('ck_warehouse_events_valid_status', 'warehouse_events', type_='check')
    op.drop_constraint('ck_shipments_valid_status', 'shipments', type_='check')
    op.drop_constraint('ck_order_items_quantity_positive', 'order_items', type_='check')

