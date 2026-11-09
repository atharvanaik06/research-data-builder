"""Allow bounded automatic job retries.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Permit three numbered build attempts for one temporary provider failure chain."""
    op.alter_column("build_jobs", "max_attempts", server_default=sa.text("3"))


def downgrade() -> None:
    """Restore one build attempt for each job."""
    op.execute(sa.text("UPDATE build_jobs SET max_attempts = 1 WHERE max_attempts > 1"))
    op.alter_column("build_jobs", "max_attempts", server_default=sa.text("1"))
