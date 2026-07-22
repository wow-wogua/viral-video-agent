"""Add durable vNext-A clarification state."""

from alembic import op
import sqlalchemy as sa


revision = "20260722_0002"
down_revision = "20260713_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_jobs", sa.Column("clarification_round", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("analysis_jobs", sa.Column("execution_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("analysis_jobs", sa.Column("topic_spec", sa.JSON(), nullable=True))
    op.add_column("analysis_jobs", sa.Column("interaction_usage", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))
    op.create_table(
        "job_clarifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("question", sa.String(length=500), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("allow_custom", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("selected_option_id", sa.String(length=64), nullable=True),
        sa.Column("custom_answer", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_job_clarifications_request_id"),
        sa.UniqueConstraint("job_id", "round", name="uq_job_clarifications_job_round"),
    )
    op.create_index("ix_job_clarifications_job_id", "job_clarifications", ["job_id"])
    op.create_index("ix_job_clarifications_status", "job_clarifications", ["status"])


def downgrade() -> None:
    op.drop_index("ix_job_clarifications_status", table_name="job_clarifications")
    op.drop_index("ix_job_clarifications_job_id", table_name="job_clarifications")
    op.drop_table("job_clarifications")
    op.drop_column("analysis_jobs", "interaction_usage")
    op.drop_column("analysis_jobs", "topic_spec")
    op.drop_column("analysis_jobs", "execution_version")
    op.drop_column("analysis_jobs", "clarification_round")
