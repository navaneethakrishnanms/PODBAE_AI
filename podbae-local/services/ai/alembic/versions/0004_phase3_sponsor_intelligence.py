"""phase 3: Layer 2 sponsor intelligence (brands, brand_domains, sponsorship_events, sponsor_reviews,
brand_registrations, sponsor_scan_runs) + opportunity_runs.kind (partner | sponsor)

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('opportunity_runs') as b:
        b.add_column(sa.Column('kind', sa.String(10), nullable=False, server_default='partner'))
    op.create_table('brands',
                    sa.Column('id', sa.String(40), primary_key=True),
                    sa.Column('name', sa.String(200), nullable=False),
                    sa.Column('name_key', sa.String(200), nullable=False),
                    sa.Column('primary_domain', sa.String(200), nullable=True, unique=True),
                    sa.Column('identity', sa.String(20), nullable=False),
                    sa.Column('aliases', sa.JSON(), nullable=False),
                    sa.Column('parent_brand_id', sa.String(40), nullable=True),
                    sa.Column('status', sa.String(10), nullable=False),
                    sa.Column('categories', sa.JSON(), nullable=False),
                    sa.Column('category_method', sa.String(20), nullable=False),
                    sa.Column('domain_verified', sa.Boolean(), nullable=False),
                    sa.Column('first_seen', sa.DateTime(), nullable=True),
                    sa.Column('last_seen', sa.DateTime(), nullable=True),
                    sa.Column('n_shows', sa.Integer(), nullable=False),
                    sa.Column('n_events', sa.Integer(), nullable=False),
                    sa.Column('merged_into', sa.String(40), nullable=True),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False))
    op.create_index('ix_brand_name_key', 'brands', ['name_key'])
    op.create_table('brand_domains',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('domain', sa.String(200), nullable=False, unique=True),
                    sa.Column('brand_id', sa.String(40), sa.ForeignKey('brands.id'), nullable=False),
                    sa.Column('source', sa.String(20), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_table('sponsorship_events',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('key', sa.String(64), nullable=False, unique=True),
                    sa.Column('show_id', sa.String(40), nullable=False),
                    sa.Column('episode_id', sa.String(40), nullable=False),
                    sa.Column('episode_date', sa.DateTime(), nullable=True),
                    sa.Column('source', sa.String(20), nullable=False),
                    sa.Column('cls', sa.String(30), nullable=False),
                    sa.Column('rule', sa.String(60), nullable=False),
                    sa.Column('snippet', sa.String(300), nullable=False),
                    sa.Column('url', sa.Text(), nullable=True),
                    sa.Column('domain', sa.String(200), nullable=True),
                    sa.Column('brand_name', sa.String(200), nullable=True),
                    sa.Column('brand_id', sa.String(40), nullable=True),
                    sa.Column('promo_code', sa.String(40), nullable=True),
                    sa.Column('method', sa.String(80), nullable=False),
                    sa.Column('model_version', sa.String(80), nullable=True),
                    sa.Column('detector_version', sa.String(30), nullable=False),
                    sa.Column('verification_status', sa.String(20), nullable=False),
                    sa.Column('reviewed_class', sa.String(30), nullable=True),
                    sa.Column('sample_bucket', sa.Integer(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False))
    for name, cols in (('ix_spev_show', ['show_id']), ('ix_spev_brand', ['brand_id', 'cls']), ('ix_spev_cls', ['cls']),
                       ('ix_spev_episode', ['episode_id'])):
        op.create_index(name, 'sponsorship_events', cols)
    op.create_table('sponsor_reviews',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('event_id', sa.Integer(), nullable=False),
                    sa.Column('reviewer', sa.String(80), nullable=False),
                    sa.Column('verdict', sa.String(10), nullable=False),
                    sa.Column('correct_class', sa.String(30), nullable=True),
                    sa.Column('original_class', sa.String(30), nullable=False),
                    sa.Column('note', sa.Text(), nullable=True),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False),
                    sa.UniqueConstraint('event_id', 'reviewer', name='uq_sponsor_review'))
    op.create_table('brand_registrations',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('brand_id', sa.String(40), nullable=False),
                    sa.Column('advertiser_ref', sa.String(60), nullable=False),
                    sa.Column('active_campaign', sa.Boolean(), nullable=False),
                    sa.Column('campaign_categories', sa.JSON(), nullable=False),
                    sa.Column('campaign_started_at', sa.DateTime(), nullable=True),
                    sa.Column('linked_by', sa.String(20), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=False),
                    sa.UniqueConstraint('brand_id', 'advertiser_ref', name='uq_brand_registration'))
    op.create_table('sponsor_scan_runs',
                    sa.Column('id', sa.String(40), primary_key=True),
                    sa.Column('detector_version', sa.String(30), nullable=False),
                    sa.Column('method', sa.String(80), nullable=False),
                    sa.Column('shows', sa.Integer(), nullable=False),
                    sa.Column('episodes', sa.Integer(), nullable=False),
                    sa.Column('transcripts', sa.Integer(), nullable=False),
                    sa.Column('events', sa.Integer(), nullable=False),
                    sa.Column('by_class', sa.JSON(), nullable=False),
                    sa.Column('seconds', sa.Float(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False))


def downgrade() -> None:
    for t in ('sponsor_scan_runs', 'brand_registrations', 'sponsor_reviews', 'sponsorship_events', 'brand_domains', 'brands'):
        op.drop_table(t)
    with op.batch_alter_table('opportunity_runs') as b:
        b.drop_column('kind')
