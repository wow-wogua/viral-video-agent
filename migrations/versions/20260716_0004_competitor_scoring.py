"""add P0-C creator audits and competitor scoring

Revision ID: 20260716_0004
Revises: 20260716_0003
Create Date: 2026-07-16
"""

from alembic import op
import sqlalchemy as sa


revision = "20260716_0004"
down_revision = "20260716_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("crawl_runs", sa.Column("snapshot_revision", sa.String(32), nullable=True))
    op.add_column("crawl_run_videos", sa.Column("relevance_labeler", sa.String(40), nullable=True))
    op.add_column("crawl_run_videos", sa.Column("relevance_labeler_version", sa.String(80), nullable=True))

    op.create_table(
        "creator_audits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("crawl_run_id", sa.Uuid(), nullable=False),
        sa.Column("creator_mid", sa.String(32), nullable=False),
        sa.Column("creator_name", sa.Text(), nullable=False),
        sa.Column("profile_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_name", sa.String(80), nullable=False),
        sa.Column("provider_version", sa.String(80), nullable=False),
        sa.Column("provider_kind", sa.String(20), nullable=False),
        sa.Column("source_provider_name", sa.String(80), nullable=False),
        sa.Column("source_provider_version", sa.String(80), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("follower_count", sa.Integer(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("recent_30d_upload_count", sa.Integer(), nullable=False),
        sa.Column("recent_90d_upload_count", sa.Integer(), nullable=False),
        sa.Column("qualification_status", sa.String(32), nullable=False),
        sa.Column("generalist", sa.Boolean(), nullable=True),
        sa.Column("risk_flags", sa.JSON(), nullable=False),
        sa.Column("assessment_reason", sa.Text(), nullable=False),
        sa.Column("assessment_confidence", sa.Float(), nullable=False),
        sa.Column("missing_reason", sa.Text(), nullable=True),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("raw_payload_hash", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["creator_mid"], ["creators.mid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crawl_run_id", "creator_mid", name="uq_creator_audit_run_mid"),
    )
    op.create_index("ix_creator_audits_crawl_run_id", "creator_audits", ["crawl_run_id"])
    op.create_index("ix_creator_audits_creator_mid", "creator_audits", ["creator_mid"])

    op.create_table(
        "creator_sample_videos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("crawl_run_id", sa.Uuid(), nullable=False),
        sa.Column("creator_mid", sa.String(32), nullable=False),
        sa.Column("bvid", sa.String(12), nullable=False),
        sa.Column("sample_rank", sa.Integer(), nullable=False),
        sa.Column("creator_name", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("partition", sa.String(80), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("view", sa.Integer(), nullable=True),
        sa.Column("like", sa.Integer(), nullable=True),
        sa.Column("coin", sa.Integer(), nullable=True),
        sa.Column("favorite", sa.Integer(), nullable=True),
        sa.Column("reply", sa.Integer(), nullable=True),
        sa.Column("share", sa.Integer(), nullable=True),
        sa.Column("danmaku", sa.Integer(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_name", sa.String(80), nullable=False),
        sa.Column("provider_version", sa.String(80), nullable=False),
        sa.Column("missing_fields", sa.JSON(), nullable=False),
        sa.Column("raw_payload_hash", sa.String(64), nullable=True),
        sa.Column("relevance_label", sa.String(20), nullable=False),
        sa.Column("relevance_reason", sa.Text(), nullable=False),
        sa.Column("relevance_confidence", sa.Float(), nullable=False),
        sa.Column("relevance_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("relevance_labeler", sa.String(40), nullable=False),
        sa.Column("relevance_labeler_version", sa.String(80), nullable=False),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["creator_mid"], ["creators.mid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bvid"], ["videos.bvid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crawl_run_id", "creator_mid", "bvid", name="uq_creator_sample_video"),
    )
    op.create_index("ix_creator_sample_videos_crawl_run_id", "creator_sample_videos", ["crawl_run_id"])
    op.create_index("ix_creator_sample_videos_creator_mid", "creator_sample_videos", ["creator_mid"])
    op.create_index("ix_creator_sample_videos_bvid", "creator_sample_videos", ["bvid"])

    op.add_column("competitor_scores", sa.Column("creator_name", sa.Text(), nullable=False, server_default=""))
    op.add_column("competitor_scores", sa.Column("component_details", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    op.add_column("competitor_scores", sa.Column("qualification_status", sa.String(32), nullable=False, server_default="discovery_only"))
    op.add_column("competitor_scores", sa.Column("search_candidate_sources", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("competitor_scores", sa.Column("creator_sample_sources", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("competitor_scores", sa.Column("tie_break_values", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("competitor_scores", sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade() -> None:
    op.drop_column("competitor_scores", "created_at")
    op.drop_column("competitor_scores", "tie_break_values")
    op.drop_column("competitor_scores", "creator_sample_sources")
    op.drop_column("competitor_scores", "search_candidate_sources")
    op.drop_column("competitor_scores", "qualification_status")
    op.drop_column("competitor_scores", "component_details")
    op.drop_column("competitor_scores", "creator_name")

    op.drop_index("ix_creator_sample_videos_bvid", table_name="creator_sample_videos")
    op.drop_index("ix_creator_sample_videos_creator_mid", table_name="creator_sample_videos")
    op.drop_index("ix_creator_sample_videos_crawl_run_id", table_name="creator_sample_videos")
    op.drop_table("creator_sample_videos")

    op.drop_index("ix_creator_audits_creator_mid", table_name="creator_audits")
    op.drop_index("ix_creator_audits_crawl_run_id", table_name="creator_audits")
    op.drop_table("creator_audits")

    op.drop_column("crawl_run_videos", "relevance_labeler_version")
    op.drop_column("crawl_run_videos", "relevance_labeler")
    op.drop_column("crawl_runs", "snapshot_revision")
