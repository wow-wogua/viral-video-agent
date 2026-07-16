"""preserve immutable per-crawl-run search observations

Revision ID: 20260716_0003
Revises: 20260715_0002
Create Date: 2026-07-16
"""

from alembic import op
import sqlalchemy as sa


revision = "20260716_0003"
down_revision = "20260715_0002"
branch_labels = None
depends_on = None


VIDEO_OBSERVATION_COLUMNS = [
    sa.Column("aid", sa.Integer(), nullable=True),
    sa.Column("creator_mid", sa.String(32), nullable=True),
    sa.Column("creator_name", sa.Text(), nullable=True),
    sa.Column("title", sa.Text(), nullable=True),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("tags", sa.JSON(), nullable=True),
    sa.Column("partition", sa.String(80), nullable=True),
    sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("duration_seconds", sa.Integer(), nullable=True),
    sa.Column("cover_url", sa.Text(), nullable=True),
    sa.Column("source_url", sa.Text(), nullable=True),
    sa.Column("view", sa.Integer(), nullable=True),
    sa.Column("like", sa.Integer(), nullable=True),
    sa.Column("coin", sa.Integer(), nullable=True),
    sa.Column("favorite", sa.Integer(), nullable=True),
    sa.Column("reply", sa.Integer(), nullable=True),
    sa.Column("share", sa.Integer(), nullable=True),
    sa.Column("danmaku", sa.Integer(), nullable=True),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("provider_name", sa.String(80), nullable=True),
    sa.Column("provider_version", sa.String(40), nullable=True),
    sa.Column("missing_fields", sa.JSON(), nullable=True),
]


def upgrade() -> None:
    op.drop_constraint("crawl_runs_job_id_fkey", "crawl_runs", type_="foreignkey")
    op.create_foreign_key(
        "fk_crawl_runs_job_id",
        "crawl_runs",
        "analysis_jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )

    for column in VIDEO_OBSERVATION_COLUMNS:
        op.add_column("crawl_run_videos", column)

    op.execute(
        """
        UPDATE crawl_run_videos AS observation
        SET
            aid = video.aid,
            creator_mid = video.creator_mid,
            creator_name = video.creator_name,
            title = video.title,
            description = video.description,
            tags = video.tags,
            partition = video.partition,
            published_at = video.published_at,
            duration_seconds = video.duration_seconds,
            cover_url = video.cover_url,
            source_url = video.source_url,
            view = video.view,
            "like" = video."like",
            coin = video.coin,
            favorite = video.favorite,
            reply = video.reply,
            share = video.share,
            danmaku = video.danmaku,
            observed_at = video.observed_at,
            provider_name = video.provider_name,
            provider_version = video.provider_version,
            missing_fields = video.missing_fields
        FROM videos AS video
        WHERE video.bvid = observation.bvid
        """
    )
    for column_name, column_type in [
        ("title", sa.Text()),
        ("tags", sa.JSON()),
        ("source_url", sa.Text()),
        ("observed_at", sa.DateTime(timezone=True)),
        ("provider_name", sa.String(80)),
        ("provider_version", sa.String(40)),
        ("missing_fields", sa.JSON()),
    ]:
        op.alter_column(
            "crawl_run_videos",
            column_name,
            existing_type=column_type,
            nullable=False,
        )
    op.create_index("ix_crawl_run_videos_creator_mid", "crawl_run_videos", ["creator_mid"])

    op.create_table(
        "crawl_run_creators",
        sa.Column("crawl_run_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("crawl_run_id", "mid"),
    )
    op.create_index("ix_crawl_run_creators_mid", "crawl_run_creators", ["mid"])
    op.execute(
        """
        INSERT INTO crawl_run_creators (
            crawl_run_id,
            mid,
            name,
            profile_url,
            avatar_url,
            follower_count,
            observed_at,
            provider_name,
            provider_version,
            recent_sample_availability,
            recent_sample_count,
            missing_reason
        )
        SELECT DISTINCT
            observation.crawl_run_id,
            creator.mid,
            creator.name,
            creator.profile_url,
            creator.avatar_url,
            creator.follower_count,
            creator.observed_at,
            creator.provider_name,
            creator.provider_version,
            creator.recent_sample_availability,
            creator.recent_sample_count,
            creator.missing_reason
        FROM crawl_run_videos AS observation
        JOIN creators AS creator ON creator.mid = observation.creator_mid
        """
    )


def downgrade() -> None:
    op.drop_index("ix_crawl_run_creators_mid", table_name="crawl_run_creators")
    op.drop_table("crawl_run_creators")
    op.drop_index("ix_crawl_run_videos_creator_mid", table_name="crawl_run_videos")
    for column in reversed(VIDEO_OBSERVATION_COLUMNS):
        op.drop_column("crawl_run_videos", column.name)

    op.drop_constraint("fk_crawl_runs_job_id", "crawl_runs", type_="foreignkey")
    op.create_foreign_key(
        "crawl_runs_job_id_fkey",
        "crawl_runs",
        "analysis_jobs",
        ["job_id"],
        ["id"],
        ondelete="SET NULL",
    )
