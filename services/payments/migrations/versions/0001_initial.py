"""Create payments and processed events

Revision ID: 0001
Revises:
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

payment_status = sa.Enum(
    "requires_payment", "succeeded", "failed", "refund_required", "amount_mismatch", name="payment_status"
)


def upgrade():
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_number", sa.String(length=20), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=100), nullable=False),
        sa.Column("client_secret", sa.String(length=255), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", payment_status, nullable=False),
        sa.Column("last_error", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="payment_amount_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_number"),
        sa.UniqueConstraint("provider_payment_id"),
    )
    op.create_index(op.f("ix_payments_user_id"), "payments", ["user_id"], unique=False)
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )


def downgrade():
    op.drop_table("processed_events")
    op.drop_index(op.f("ix_payments_user_id"), table_name="payments")
    op.drop_table("payments")
    payment_status.drop(op.get_bind(), checkfirst=True)
