"""Add cooperative build cancellation.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BUILD_STATUS_WITH_CANCELLED = (
    "status IN ('planned', 'queued', 'retrieving', 'transforming', "
    "'validating', 'exporting', 'succeeded', 'failed', 'cancelled')"
)
BUILD_STATUS_WITHOUT_CANCELLED = (
    "status IN ('planned', 'queued', 'retrieving', 'transforming', "
    "'validating', 'exporting', 'succeeded', 'failed')"
)
JOB_STATUS_WITH_CANCELLED = "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')"
JOB_STATUS_WITHOUT_CANCELLED = "status IN ('queued', 'running', 'succeeded', 'failed')"


def upgrade() -> None:
    """Add cancellation states and the cancellation request time."""
    op.drop_constraint(op.f("ck_build_runs_build_status"), "build_runs", type_="check")
    op.create_check_constraint("build_status", "build_runs", BUILD_STATUS_WITH_CANCELLED)
    op.drop_constraint(op.f("ck_build_jobs_job_status"), "build_jobs", type_="check")
    op.create_check_constraint("job_status", "build_jobs", JOB_STATUS_WITH_CANCELLED)
    op.add_column(
        "build_jobs",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove cancellation states and requests."""
    op.execute(
        sa.text(
            "UPDATE build_runs SET status = 'failed', "
            "error_code = 'cancelled_by_user' WHERE status = 'cancelled'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE build_jobs SET status = 'failed', progress = 'failed', "
            "error_code = 'cancelled_by_user' WHERE status = 'cancelled'"
        )
    )
    op.drop_column("build_jobs", "cancel_requested_at")
    op.drop_constraint(op.f("ck_build_jobs_job_status"), "build_jobs", type_="check")
    op.create_check_constraint("job_status", "build_jobs", JOB_STATUS_WITHOUT_CANCELLED)
    op.drop_constraint(op.f("ck_build_runs_build_status"), "build_runs", type_="check")
    op.create_check_constraint("build_status", "build_runs", BUILD_STATUS_WITHOUT_CANCELLED)
