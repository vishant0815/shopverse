"""Recipients, order owners, the notification log and processed messages.

Revision ID: 0001
Revises:
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recipients",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("first_name", sa.String(150), nullable=False),
        sa.Column("last_name", sa.String(150), nullable=False),
    )
    op.create_table(
        "order_customers",
        sa.Column("order_number", sa.String(20), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
    )
    op.create_index("ix_order_customers_user_id", "order_customers", ["user_id"])
    op.create_table(
        "notification_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("order_number", sa.String(20), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notification_log_message_id", "notification_log", ["message_id"])
    op.create_index("ix_notification_log_order_number", "notification_log", ["order_number"])
    op.create_index("ix_notification_log_user_id", "notification_log", ["user_id"])
    op.create_table(
        "processed_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("topic", sa.String(100), nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("processed_messages")
    op.drop_table("notification_log")
    op.drop_table("order_customers")
    op.drop_table("recipients")
