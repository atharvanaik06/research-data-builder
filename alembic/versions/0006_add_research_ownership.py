"""Add user ownership to recipes and builds.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_OWNER_ID = "00000000-0000-4000-8000-000000000007"


def upgrade() -> None:
    """Preserve existing rows under an inactive owner and require ownership thereafter."""
    op.execute(
        sa.text(
            "INSERT INTO users (id, email, password_hash, is_active) "
            "VALUES (:id, :email, :password_hash, false)"
        ).bindparams(
            id=LEGACY_OWNER_ID,
            email="legacy-owner@research-data-builder.invalid",
            password_hash="disabled-migration-owner",
        )
    )

    op.add_column("dataset_recipes", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text("UPDATE dataset_recipes SET owner_id = :owner_id").bindparams(
            owner_id=LEGACY_OWNER_ID
        )
    )
    op.alter_column("dataset_recipes", "owner_id", nullable=False)
    op.create_foreign_key(
        "fk_dataset_recipes_owner_id_users",
        "dataset_recipes",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_dataset_recipes_owner_id", "dataset_recipes", ["owner_id"])

    op.add_column("build_runs", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE build_runs AS build "
            "SET owner_id = recipe.owner_id "
            "FROM recipe_versions AS version "
            "JOIN dataset_recipes AS recipe ON recipe.id = version.recipe_id "
            "WHERE build.recipe_version_id = version.id"
        )
    )
    op.alter_column("build_runs", "owner_id", nullable=False)
    op.create_foreign_key(
        "fk_build_runs_owner_id_users",
        "build_runs",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_build_runs_owner_id", "build_runs", ["owner_id"])
    op.drop_constraint("uq_build_runs_identity", "build_runs", type_="unique")
    op.create_unique_constraint(
        "uq_build_runs_version_identity",
        "build_runs",
        ["recipe_version_id", "build_identity"],
    )


def downgrade() -> None:
    """Remove research ownership while preserving recipe and build rows."""
    op.drop_constraint("uq_build_runs_version_identity", "build_runs", type_="unique")
    op.create_unique_constraint("uq_build_runs_identity", "build_runs", ["build_identity"])
    op.drop_index("ix_build_runs_owner_id", table_name="build_runs")
    op.drop_constraint("fk_build_runs_owner_id_users", "build_runs", type_="foreignkey")
    op.drop_column("build_runs", "owner_id")
    op.drop_index("ix_dataset_recipes_owner_id", table_name="dataset_recipes")
    op.drop_constraint("fk_dataset_recipes_owner_id_users", "dataset_recipes", type_="foreignkey")
    op.drop_column("dataset_recipes", "owner_id")
    op.execute(sa.text("DELETE FROM users WHERE id = :id").bindparams(id=LEGACY_OWNER_ID))
