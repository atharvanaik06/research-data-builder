"""Add immutable numbered build attempts.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Number build attempts and allow a failed build to be retried as a new row."""
    op.add_column(
        "build_runs",
        sa.Column("attempt_number", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_check_constraint(
        "build_attempt_number_positive",
        "build_runs",
        "attempt_number > 0",
    )
    op.drop_constraint("uq_build_runs_version_identity", "build_runs", type_="unique")
    op.create_unique_constraint(
        "uq_build_runs_version_identity_attempt",
        "build_runs",
        ["recipe_version_id", "build_identity", "attempt_number"],
    )


def downgrade() -> None:
    """Return to one build row per version and deterministic plan identity."""
    op.drop_constraint("uq_build_runs_version_identity_attempt", "build_runs", type_="unique")
    op.create_unique_constraint(
        "uq_build_runs_version_identity",
        "build_runs",
        ["recipe_version_id", "build_identity"],
    )
    op.drop_constraint("build_attempt_number_positive", "build_runs", type_="check")
    op.drop_column("build_runs", "attempt_number")
