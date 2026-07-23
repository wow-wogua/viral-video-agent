"""Add vNext-B revision audit and dispatch reconciliation state."""

from alembic import op
import sqlalchemy as sa


revision = "20260723_0003"
down_revision = "20260722_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("revision_of_job_id", sa.Uuid(), nullable=True))
    op.add_column("analysis_jobs", sa.Column("dispatch_pending_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_analysis_jobs_revision_of_job_id",
        "analysis_jobs",
        "analysis_jobs",
        ["revision_of_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_analysis_jobs_revision_of_job_id", "analysis_jobs", ["revision_of_job_id"])
    op.create_index("ix_analysis_jobs_pending_dispatch", "analysis_jobs", ["status", "dispatch_pending_at"])
    op.execute(
        "UPDATE analysis_jobs SET dispatch_pending_at = created_at "
        "WHERE status = 'pending' AND arq_job_id IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_jobs_pending_dispatch", table_name="analysis_jobs")
    op.drop_index("ix_analysis_jobs_revision_of_job_id", table_name="analysis_jobs")
    op.drop_constraint("fk_analysis_jobs_revision_of_job_id", "analysis_jobs", type_="foreignkey")
    op.drop_column("analysis_jobs", "dispatch_pending_at")
    op.drop_column("analysis_jobs", "revision_of_job_id")
