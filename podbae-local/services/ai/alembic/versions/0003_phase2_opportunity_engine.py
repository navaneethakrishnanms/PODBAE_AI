"""phase 2: Layer 4 opportunity engine (podcast partners): runs, opportunities, gate rejections, events, blind pair labels;
show_claims.demo

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('show_claims') as b:
        b.add_column(sa.Column('demo', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('opportunity_runs',
                    sa.Column('id', sa.String(40), primary_key=True),
                    sa.Column('member_show_id', sa.String(40), nullable=False),
                    sa.Column('scoring_version', sa.String(40), nullable=False),
                    sa.Column('config_hash', sa.String(20), nullable=False),
                    sa.Column('inputs_fingerprint', sa.String(64), nullable=False),
                    sa.Column('as_of', sa.DateTime(), nullable=False),
                    sa.Column('n_candidates', sa.Integer(), nullable=False),
                    sa.Column('n_rejected', sa.Integer(), nullable=False),
                    sa.Column('n_scored', sa.Integer(), nullable=False),
                    sa.Column('n_qualified', sa.Integer(), nullable=False),
                    sa.Column('duration_ms', sa.Integer(), nullable=False),
                    sa.Column('result_hash', sa.String(64), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_orun_member', 'opportunity_runs', ['member_show_id', 'created_at'])
    op.create_table('opportunities',
                    sa.Column('id', sa.String(40), primary_key=True),
                    sa.Column('member_show_id', sa.String(40), nullable=False),
                    sa.Column('type', sa.String(20), nullable=False),
                    sa.Column('target_show_id', sa.String(40), nullable=False),
                    sa.Column('fit', sa.Float(), nullable=False),
                    sa.Column('breakdown_json', sa.JSON(), nullable=False),
                    sa.Column('confidence', sa.Float(), nullable=False),
                    sa.Column('confidence_level', sa.String(10), nullable=False),
                    sa.Column('readiness', sa.String(20), nullable=False),
                    sa.Column('conversion_status', sa.String(30), nullable=False),
                    sa.Column('why_now_json', sa.JSON(), nullable=False),
                    sa.Column('evidence_ids', sa.JSON(), nullable=False),
                    sa.Column('explanation_json', sa.JSON(), nullable=False),
                    sa.Column('scoring_version', sa.String(40), nullable=False),
                    sa.Column('feature_snapshot_json', sa.JSON(), nullable=False),
                    sa.Column('inputs_hash', sa.String(64), nullable=False),
                    sa.Column('qualified', sa.Boolean(), nullable=False),
                    sa.Column('rank', sa.Integer(), nullable=True),
                    sa.Column('status', sa.String(20), nullable=False),
                    sa.Column('run_id', sa.String(40), nullable=True),
                    sa.Column('expires_at', sa.DateTime(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_index('ix_opp_member_status', 'opportunities', ['member_show_id', 'status'])
    op.create_index('ix_opp_member_target', 'opportunities', ['member_show_id', 'target_show_id'])
    op.create_table('opportunity_rejections',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('run_id', sa.String(40), nullable=False),
                    sa.Column('member_show_id', sa.String(40), nullable=False),
                    sa.Column('candidate_show_id', sa.String(40), nullable=False),
                    sa.Column('reason', sa.String(40), nullable=False),
                    sa.Column('detail', sa.JSON(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_orej_run', 'opportunity_rejections', ['run_id'])
    op.create_index('ix_orej_reason', 'opportunity_rejections', ['reason'])
    op.create_table('opportunity_events',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('opportunity_id', sa.String(40), nullable=False),
                    sa.Column('member_show_id', sa.String(40), nullable=False),
                    sa.Column('target_show_id', sa.String(40), nullable=False),
                    sa.Column('user_id', sa.String(40), nullable=True),
                    sa.Column('type', sa.String(20), nullable=False),
                    sa.Column('position', sa.Integer(), nullable=True),
                    sa.Column('reason', sa.String(40), nullable=True),
                    sa.Column('note', sa.Text(), nullable=True),
                    sa.Column('scoring_version', sa.String(40), nullable=False),
                    sa.Column('idempotency_key', sa.String(200), nullable=True, unique=True),
                    sa.Column('ts', sa.DateTime(), nullable=False))
    op.create_index('ix_oevt_member_target', 'opportunity_events', ['member_show_id', 'target_show_id', 'type'])
    op.create_index('ix_oevt_opp', 'opportunity_events', ['opportunity_id'])
    op.create_table('pair_label_items',
                    sa.Column('member_show_id', sa.String(40), primary_key=True),
                    sa.Column('position', sa.Integer(), nullable=False),
                    sa.Column('engine_top', sa.JSON(), nullable=False),
                    sa.Column('legacy_top', sa.JSON(), nullable=False),
                    sa.Column('scoring_version', sa.String(40), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_table('pair_labels',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('member_show_id', sa.String(40), nullable=False),
                    sa.Column('candidate_show_id', sa.String(40), nullable=False),
                    sa.Column('labeler', sa.String(80), nullable=False),
                    sa.Column('rating', sa.String(8), nullable=False),
                    sa.Column('note', sa.Text(), nullable=True),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False),
                    sa.UniqueConstraint('member_show_id', 'candidate_show_id', 'labeler', name='uq_pair_label'))


def downgrade() -> None:
    op.drop_table('pair_labels')
    op.drop_table('pair_label_items')
    op.drop_table('opportunity_events')
    op.drop_table('opportunity_rejections')
    op.drop_table('opportunities')
    op.drop_table('opportunity_runs')
    with op.batch_alter_table('show_claims') as b:
        b.drop_column('demo')
