"""phase 4: LLM output cache + call log; LLM second-opinion columns on sponsorship_events; LLM suggestions on brands.
Everything is additive: rule values are untouched, and with the LLM switched off every new column is ignored.

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'llm_cache',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('task', sa.String(40), nullable=False),
        sa.Column('prompt_version', sa.String(40), nullable=False),
        sa.Column('model', sa.String(80), nullable=False),
        sa.Column('entity_type', sa.String(20)),
        sa.Column('entity_id', sa.String(80)),
        sa.Column('output', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_llm_cache_task', 'llm_cache', ['task', 'prompt_version'])
    op.create_table(
        'llm_calls',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ts', sa.DateTime(), nullable=False),
        sa.Column('task', sa.String(40), nullable=False),
        sa.Column('provider', sa.String(30), nullable=False),
        sa.Column('model', sa.String(80), nullable=False),
        sa.Column('prompt_version', sa.String(40), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('cache_hit', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('tokens_in', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tokens_out', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('entity_type', sa.String(20)),
        sa.Column('entity_id', sa.String(80)),
        sa.Column('error', sa.Text()),
    )
    op.create_index('ix_llm_calls_task', 'llm_calls', ['task', 'ts'])
    with op.batch_alter_table('sponsorship_events') as b:
        b.add_column(sa.Column('llm_cls', sa.String(30)))
        b.add_column(sa.Column('llm_raw_cls', sa.String(30)))
        b.add_column(sa.Column('llm_reason', sa.String(300)))
        b.add_column(sa.Column('llm_quote', sa.String(300)))
        b.add_column(sa.Column('llm_task', sa.String(30)))
        b.add_column(sa.Column('llm_version', sa.String(120)))
        b.add_column(sa.Column('llm_flag', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('brands') as b:
        b.add_column(sa.Column('llm_categories', sa.JSON()))
        b.add_column(sa.Column('llm_categories_version', sa.String(120)))
        b.add_column(sa.Column('name_suggestion', sa.String(200)))
        b.add_column(sa.Column('name_suggestion_status', sa.String(20)))
        b.add_column(sa.Column('name_suggestion_support', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('brands') as b:
        for c in ('name_suggestion_support', 'name_suggestion_status', 'name_suggestion', 'llm_categories_version', 'llm_categories'):
            b.drop_column(c)
    with op.batch_alter_table('sponsorship_events') as b:
        for c in ('llm_flag', 'llm_version', 'llm_task', 'llm_quote', 'llm_reason', 'llm_raw_cls', 'llm_cls'):
            b.drop_column(c)
    op.drop_index('ix_llm_calls_task', 'llm_calls')
    op.drop_table('llm_calls')
    op.drop_index('ix_llm_cache_task', 'llm_cache')
    op.drop_table('llm_cache')
