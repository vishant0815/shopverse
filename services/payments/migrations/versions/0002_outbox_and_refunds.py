"""Outbox and idempotent consumer tables, the received amount, and refunded payments

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    # Added to the existing enum. Postgres can't remove an enum value, so downgrade leaves it.
    op.execute("ALTER TYPE payment_status ADD VALUE IF NOT EXISTS 'refunded'")
    op.add_column("payments", sa.Column("received_amount_minor", sa.Integer(), nullable=True))

    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Sending order. See docs/events.md: a timestamp can't order rows written in one transaction.
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("topic", sa.String(length=100), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_index(
        "ix_outbox_unsent", "outbox", ["seq"], unique=False,
        postgresql_where=sa.text("published_at IS NULL"),
    )

    op.create_table(
        "processed_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(length=100), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("processed_messages")
    op.drop_index("ix_outbox_unsent", table_name="outbox")
    op.drop_table("outbox")
    op.drop_column("payments", "received_amount_minor")
