"""Create stock, reservations, the outbox and processed messages

Revision ID: 0001
Revises:
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('outbox',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('topic', sa.String(length=100), nullable=False),
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('type', sa.String(length=100), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('seq')
    )
    # The relay asks "what hasn't been sent?" constantly; only unsent rows are indexed.
    op.create_index("ix_outbox_unsent", "outbox", ["seq"], postgresql_where=sa.text("published_at IS NULL"))
    op.create_table('processed_messages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('topic', sa.String(length=100), nullable=False),
    sa.Column('type', sa.String(length=100), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('reservations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('order_number', sa.String(length=20), nullable=False),
    sa.Column('status', sa.Enum('held', 'committed', 'released', 'rejected', name='reservation_status'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('order_number')
    )
    op.create_table('stock_items',
    sa.Column('variant_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('seller_id', sa.Uuid(), nullable=False),
    sa.Column('sku', sa.String(length=64), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('on_hand', sa.Integer(), nullable=False),
    sa.Column('reserved', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('on_hand >= 0', name='on_hand_not_negative'),
    sa.CheckConstraint('reserved <= on_hand', name='reserved_within_on_hand'),
    sa.CheckConstraint('reserved >= 0', name='reserved_not_negative'),
    sa.PrimaryKeyConstraint('variant_id')
    )
    op.create_index(op.f('ix_stock_items_product_id'), 'stock_items', ['product_id'], unique=False)
    op.create_index(op.f('ix_stock_items_seller_id'), 'stock_items', ['seller_id'], unique=False)
    op.create_table('reservation_lines',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('reservation_id', sa.Uuid(), nullable=False),
    sa.Column('variant_id', sa.Uuid(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.CheckConstraint('quantity > 0', name='line_quantity_positive'),
    sa.ForeignKeyConstraint(['reservation_id'], ['reservations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reservation_lines_reservation_id'), 'reservation_lines', ['reservation_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_reservation_lines_reservation_id'), table_name='reservation_lines')
    op.drop_table('reservation_lines')
    op.drop_index(op.f('ix_stock_items_seller_id'), table_name='stock_items')
    op.drop_index(op.f('ix_stock_items_product_id'), table_name='stock_items')
    op.drop_table('stock_items')
    op.drop_table('reservations')
    op.drop_table('processed_messages')
    op.drop_index("ix_outbox_unsent", table_name="outbox")
    op.drop_table('outbox')
    sa.Enum(name="reservation_status").drop(op.get_bind(), checkfirst=True)
