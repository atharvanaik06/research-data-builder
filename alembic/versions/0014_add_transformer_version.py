"""Record the transformer version that executed a build."""

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("build_runs", sa.Column("transformer_version", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("build_runs", "transformer_version")
