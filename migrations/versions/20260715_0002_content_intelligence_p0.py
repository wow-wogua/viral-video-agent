"""add P0 content-intelligence snapshot tables

Revision ID: 20260715_0002
Revises: 20260713_0001
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_0002"
down_revision = "20260713_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("task_mode", sa.String(32), nullable=False, server_default="legacy"))
    op.add_column("analysis_jobs", sa.Column("keyword", sa.Text(), nullable=True))
    op.add_column("analysis_jobs", sa.Column("sort_mode", sa.String(32), nullable=False, server_default="relevance"))
    op.add_column("analysis_jobs", sa.Column("time_range", sa.String(32), nullable=False, server_default="all"))
    op.add_column("analysis_jobs", sa.Column("partition", sa.String(80), nullable=True))
    op.add_column("analysis_jobs", sa.Column("max_pages", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("analysis_jobs", sa.Column("asr_options", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    op.add_column("analysis_jobs", sa.Column("request_filters", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))

    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("keyword", sa.Text(), nullable=False),
        sa.Column("requested_pages", sa.Integer(), nullable=False),
        sa.Column("successful_pages", sa.Integer(), nullable=False),
        sa.Column("raw_result_count", sa.Integer(), nullable=False),
        sa.Column("deduplicated_video_count", sa.Integer(), nullable=False),
        sa.Column("candidate_creator_count", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(80), nullable=False),
        sa.Column("provider_version", sa.String(40), nullable=False),
        sa.Column("sort_mode", sa.String(32), nullable=False),
        sa.Column("time_range", sa.String(32), nullable=False),
        sa.Column("partition", sa.String(80), nullable=True),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("partial_success", sa.Boolean(), nullable=False),
        sa.Column("truncation_reason", sa.Text(), nullable=True),
        sa.Column("coverage", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_crawl_runs_job_id", "crawl_runs", ["job_id"])
    op.create_index("ix_crawl_runs_status", "crawl_runs", ["status"])
    op.create_index("ix_crawl_runs_keyword_started", "crawl_runs", ["keyword", "started_at"])

    op.create_table(
        "creators",
        sa.Column("mid", sa.String(32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("follower_count", sa.Integer(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_name", sa.String(80), nullable=False),
        sa.Column("provider_version", sa.String(40), nullable=False),
        sa.Column("recent_sample_availability", sa.String(20), nullable=False),
        sa.Column("recent_sample_count", sa.Integer(), nullable=False),
        sa.Column("missing_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("mid"),
    )
    op.create_table(
        "videos",
        sa.Column("bvid", sa.String(12), nullable=False),
        sa.Column("aid", sa.Integer(), nullable=True),
        sa.Column("creator_mid", sa.String(32), nullable=True),
        sa.Column("creator_name", sa.Text(), nullable=True),
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
        sa.Column("provider_version", sa.String(40), nullable=False),
        sa.Column("missing_fields", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["creator_mid"], ["creators.mid"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("bvid"),
    )
    op.create_index("ix_videos_creator_mid", "videos", ["creator_mid"])
    op.create_table(
        "search_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("crawl_run_id", sa.Uuid(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_duration_ms", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("raw_result_count", sa.Integer(), nullable=False),
        sa.Column("normalized_result_count", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(80), nullable=False),
        sa.Column("provider_version", sa.String(40), nullable=False),
        sa.Column("native_filters", sa.JSON(), nullable=False),
        sa.Column("local_filters", sa.JSON(), nullable=False),
        sa.Column("raw_payload_hash", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crawl_run_id", "page_number", name="uq_search_page_run_number"),
    )
    op.create_index("ix_search_pages_crawl_run_id", "search_pages", ["crawl_run_id"])
    op.create_table(
        "crawl_run_videos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("crawl_run_id", sa.Uuid(), nullable=False),
        sa.Column("bvid", sa.String(12), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("result_rank", sa.Integer(), nullable=False),
        sa.Column("relevance_label", sa.String(20), nullable=False),
        sa.Column("relevance_reason", sa.Text(), nullable=True),
        sa.Column("relevance_confidence", sa.Float(), nullable=True),
        sa.Column("relevance_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("raw_payload_hash", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["bvid"], ["videos.bvid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crawl_run_id", "bvid", name="uq_crawl_run_video"),
    )
    op.create_index("ix_crawl_run_videos_bvid", "crawl_run_videos", ["bvid"])
    op.create_index("ix_crawl_run_videos_crawl_run_id", "crawl_run_videos", ["crawl_run_id"])
    op.create_table(
        "competitor_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("crawl_run_id", sa.Uuid(), nullable=False),
        sa.Column("creator_mid", sa.String(32), nullable=False),
        sa.Column("scoring_version", sa.String(40), nullable=False),
        sa.Column("component_scores", sa.JSON(), nullable=False),
        sa.Column("penalty_scores", sa.JSON(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("selection_rank", sa.Integer(), nullable=True),
        sa.Column("inclusion_reason", sa.Text(), nullable=True),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("metric_results", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["creator_mid"], ["creators.mid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crawl_run_id", "creator_mid", "scoring_version", name="uq_competitor_score_version"),
    )
    op.create_index("ix_competitor_scores_crawl_run_id", "competitor_scores", ["crawl_run_id"])
    op.create_index("ix_competitor_scores_creator_mid", "competitor_scores", ["creator_mid"])
    op.create_table(
        "representative_video_selections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("crawl_run_id", sa.Uuid(), nullable=False),
        sa.Column("creator_mid", sa.String(32), nullable=False),
        sa.Column("bvid", sa.String(12), nullable=False),
        sa.Column("selection_type", sa.String(32), nullable=False),
        sa.Column("selection_rank", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["bvid"], ["videos.bvid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["creator_mid"], ["creators.mid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crawl_run_id", "creator_mid", "bvid", name="uq_representative_video"),
    )
    op.create_index("ix_representative_video_selections_bvid", "representative_video_selections", ["bvid"])
    op.create_index("ix_representative_video_selections_crawl_run_id", "representative_video_selections", ["crawl_run_id"])
    op.create_index("ix_representative_video_selections_creator_mid", "representative_video_selections", ["creator_mid"])

    op.add_column("reports", sa.Column("crawl_run_id", sa.Uuid(), nullable=True))
    op.add_column("reports", sa.Column("intelligence_payload", sa.JSON(), nullable=True))
    op.create_foreign_key("fk_reports_crawl_run", "reports", "crawl_runs", ["crawl_run_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_reports_crawl_run_id", "reports", ["crawl_run_id"])
    op.add_column("evidence_items", sa.Column("crawl_run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_evidence_items_crawl_run", "evidence_items", "crawl_runs", ["crawl_run_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_evidence_items_crawl_run_id", "evidence_items", ["crawl_run_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_items_crawl_run_id", table_name="evidence_items")
    op.drop_constraint("fk_evidence_items_crawl_run", "evidence_items", type_="foreignkey")
    op.drop_column("evidence_items", "crawl_run_id")
    op.drop_index("ix_reports_crawl_run_id", table_name="reports")
    op.drop_constraint("fk_reports_crawl_run", "reports", type_="foreignkey")
    op.drop_column("reports", "intelligence_payload")
    op.drop_column("reports", "crawl_run_id")
    for table in [
        "representative_video_selections",
        "competitor_scores",
        "crawl_run_videos",
        "search_pages",
        "videos",
        "creators",
        "crawl_runs",
    ]:
        op.drop_table(table)
    for column in [
        "request_filters",
        "asr_options",
        "max_pages",
        "partition",
        "time_range",
        "sort_mode",
        "keyword",
        "task_mode",
    ]:
        op.drop_column("analysis_jobs", column)
