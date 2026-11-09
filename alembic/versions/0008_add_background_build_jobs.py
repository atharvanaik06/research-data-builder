"""Add durable background build jobs.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BUILD_STATUS_WITH_QUEUED = (
    "status IN ('planned', 'queued', 'retrieving', 'transforming', "
    "'validating', 'exporting', 'succeeded', 'failed')"
)
BUILD_STATUS_WITHOUT_QUEUED = (
    "status IN ('planned', 'retrieving', 'transforming', 'validating', "
    "'exporting', 'succeeded', 'failed')"
)


def upgrade() -> None:
    """Add queued build state and durable worker jobs."""
    op.drop_constraint(op.f("ck_build_runs_build_status"), "build_runs", type_="check")
    op.create_check_constraint("build_status", "build_runs", BUILD_STATUS_WITH_QUEUED)
    op.create_table(
        "build_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("build_run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(9), nullable=False),
        sa.Column("progress", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.CheckConstraint("attempt_count >= 0", name="build_job_attempt_count_nonnegative"),
        sa.CheckConstraint("max_attempts > 0", name="build_job_max_attempts_positive"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="job_status",
        ),
        sa.ForeignKeyConstraint(
            ["build_run_id"],
            ["build_runs.id"],
            name="fk_build_jobs_build_run_id_build_runs",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_build_jobs"),
        sa.UniqueConstraint("build_run_id", name="uq_build_jobs_build_run_id"),
    )
    op.create_index(
        "ix_build_jobs_claim",
        "build_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index("ix_build_jobs_lease_expires_at", "build_jobs", ["lease_expires_at"])


def downgrade() -> None:
    """Remove background jobs and the queued build state."""
    op.drop_index("ix_build_jobs_lease_expires_at", table_name="build_jobs")
    op.drop_index("ix_build_jobs_claim", table_name="build_jobs")
    op.drop_table("build_jobs")
    op.execute(sa.text("UPDATE build_runs SET status = 'planned' WHERE status = 'queued'"))
    op.drop_constraint(op.f("ck_build_runs_build_status"), "build_runs", type_="check")
    op.create_check_constraint("build_status", "build_runs", BUILD_STATUS_WITHOUT_QUEUED)
