"""phase 1: feed failure reasons, corpus calibration stats, API cache, human eval labels

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('connector_runs') as b:
        b.add_column(sa.Column('target', sa.Text(), nullable=True))
        b.add_column(sa.Column('error_kind', sa.String(length=30), nullable=True))
    op.create_table('corpus_stats',
                    sa.Column('key', sa.String(length=120), nullable=False),
                    sa.Column('value', sa.JSON(), nullable=False),
                    sa.Column('n', sa.Integer(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False),
                    sa.PrimaryKeyConstraint('key'))
    op.create_table('api_cache',
                    sa.Column('key', sa.String(length=64), nullable=False),
                    sa.Column('provider', sa.String(length=30), nullable=False),
                    sa.Column('response', sa.JSON(), nullable=False),
                    sa.Column('fetched_at', sa.DateTime(), nullable=False),
                    sa.PrimaryKeyConstraint('key'))
    op.create_table('label_items',
                    sa.Column('show_id', sa.String(length=40), nullable=False),
                    sa.Column('position', sa.Integer(), nullable=False),
                    sa.Column('category', sa.String(length=60), nullable=True),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.PrimaryKeyConstraint('show_id'))
    op.create_table('eval_labels',
                    sa.Column('id', sa.Integer(), nullable=False),
                    sa.Column('show_id', sa.String(length=40), nullable=False),
                    sa.Column('labeler', sa.String(length=80), nullable=False),
                    sa.Column('topics', sa.JSON(), nullable=False),
                    sa.Column('vibes', sa.JSON(), nullable=False),
                    sa.Column('style', sa.String(length=30), nullable=False),
                    sa.Column('guest_friendly', sa.Boolean(), nullable=False),
                    sa.Column('notes', sa.Text(), nullable=True),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False),
                    sa.PrimaryKeyConstraint('id'),
                    sa.UniqueConstraint('show_id', 'labeler', name='uq_label_show_labeler'))


def downgrade() -> None:
    op.drop_table('eval_labels')
    op.drop_table('label_items')
    op.drop_table('api_cache')
    op.drop_table('corpus_stats')
    with op.batch_alter_table('connector_runs') as b:
        b.drop_column('error_kind')
        b.drop_column('target')
