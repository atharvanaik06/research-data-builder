"""Add immutable provider input cache records.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add cached responses and build-input cache lineage."""
    op.create_table(
        "provider_input_cache",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("indicator_id", sa.String(128), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("observations", sa.JSON(), nullable=False),
        sa.Column("response_fingerprint", sa.String(64), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint("hit_count >= 0", name="provider_cache_hits_nonnegative"),
        sa.CheckConstraint("observation_count >= 0", name="provider_cache_count_nonnegative"),
        sa.CheckConstraint("length(request_key) = 64", name="provider_cache_request_key_length"),
        sa.CheckConstraint(
            "length(response_fingerprint) = 64",
            name="provider_cache_response_fingerprint_length",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_input_cache")),
    )
    op.create_index(
        "ix_provider_input_cache_lookup",
        "provider_input_cache",
        ["request_key", "expires_at", "retrieved_at"],
    )
    op.add_column(
        "build_jobs",
        sa.Column("force_refresh", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("build_inputs", sa.Column("cache_entry_id", sa.Uuid(), nullable=True))
    op.add_column("build_inputs", sa.Column("cache_status", sa.String(16), nullable=True))
    op.add_column(
        "build_inputs", sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_build_inputs_cache_entry_id_provider_input_cache"),
        "build_inputs",
        "provider_input_cache",
        ["cache_entry_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Remove provider cache records and cache lineage."""
    op.drop_constraint(
        op.f("fk_build_inputs_cache_entry_id_provider_input_cache"),
        "build_inputs",
        type_="foreignkey",
    )
    op.drop_column("build_inputs", "retrieved_at")
    op.drop_column("build_inputs", "cache_status")
    op.drop_column("build_inputs", "cache_entry_id")
    op.drop_column("build_jobs", "force_refresh")
    op.drop_index("ix_provider_input_cache_lookup", table_name="provider_input_cache")
    op.drop_table("provider_input_cache")
