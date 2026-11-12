"""Link replay attempts to their original build."""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("build_runs", sa.Column("replay_of_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_build_runs_replay_source",
        "build_runs",
        "build_runs",
        ["replay_of_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_build_runs_replay_source", "build_runs", type_="foreignkey")
    op.drop_column("build_runs", "replay_of_id")
