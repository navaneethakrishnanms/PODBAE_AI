"""phase 3: opportunity_runs.stats (compact distributions of every scored candidate; below-threshold rows are no longer
stored in full)

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('opportunity_runs') as b:
        b.add_column(sa.Column('stats', sa.JSON(), nullable=False, server_default='{}'))


def downgrade() -> None:
    with op.batch_alter_table('opportunity_runs') as b:
        b.drop_column('stats')
