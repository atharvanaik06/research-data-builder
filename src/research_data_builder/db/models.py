"""SQLAlchemy models for append-only economic observation history."""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from research_data_builder.db.base import Base


class SyncStatus(StrEnum):
    """Lifecycle states for one synchronization attempt."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ChangeType(StrEnum):
    """Meaningful changes emitted by the future revision engine."""

    NEW = "new"
    REVISED = "revised"
    REMOVED = "removed"
    MISSING = "missing"
    METADATA_CHANGED = "metadata_changed"


class BuildStatus(StrEnum):
    """Lifecycle states for a dataset build."""

    PLANNED = "planned"
    QUEUED = "queued"
    RETRIEVING = "retrieving"
    TRANSFORMING = "transforming"
    VALIDATING = "validating"
    EXPORTING = "exporting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobStatus(StrEnum):
    """Lifecycle states for one background build job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def enum_values(enum_type: type[StrEnum]) -> list[str]:
    """Persist string-enum values instead of Python member names."""
    return [member.value for member in enum_type]


class User(Base):
    """One authenticated researcher account."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint("length(email) > 3", name="user_email_not_empty"),
        CheckConstraint("length(password_hash) > 0", name="user_password_hash_not_empty"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user")
    recipes: Mapped[list["DatasetRecipe"]] = relationship(back_populates="owner")
    build_runs: Mapped[list["BuildRun"]] = relationship(back_populates="owner")


class UserSession(Base):
    """Revocable server-side browser session identified by a token hash."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
        CheckConstraint("length(token_hash) = 64", name="user_session_token_hash_length"),
        Index("ix_user_sessions_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="sessions")


class Series(Base):
    """One economic series tracked from an external provider."""

    __tablename__ = "series"
    __table_args__ = (
        UniqueConstraint("provider", "provider_series_id", name="uq_series_provider_identity"),
        CheckConstraint("length(provider) > 0", name="provider_not_empty"),
        CheckConstraint("length(provider_series_id) > 0", name="provider_series_id_not_empty"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(32))
    provider_series_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(255))
    units: Mapped[str] = mapped_column(String(128))
    frequency: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_fingerprint: Mapped[str | None] = mapped_column(String(64))
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sync_runs: Mapped[list["SyncRun"]] = relationship(back_populates="series")
    observation_versions: Mapped[list["ObservationVersion"]] = relationship(back_populates="series")
    change_events: Mapped[list["ChangeEvent"]] = relationship(back_populates="series")


class SyncRun(Base):
    """Audit record for one attempt to synchronize a series."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint("new_count >= 0", name="new_count_nonnegative"),
        CheckConstraint("revised_count >= 0", name="revised_count_nonnegative"),
        CheckConstraint("unchanged_count >= 0", name="unchanged_count_nonnegative"),
        CheckConstraint("removed_count >= 0", name="removed_count_nonnegative"),
        CheckConstraint("missing_count >= 0", name="missing_count_nonnegative"),
        CheckConstraint(
            "(status = 'running' AND finished_at IS NULL) OR "
            "(status IN ('succeeded', 'failed') AND finished_at IS NOT NULL)",
            name="status_matches_finished_at",
        ),
        Index("ix_sync_runs_series_started", "series_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    series_id: Mapped[UUID] = mapped_column(
        ForeignKey("series.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[SyncStatus] = mapped_column(
        Enum(
            SyncStatus,
            name="sync_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=SyncStatus.RUNNING,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    new_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    revised_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    removed_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    missing_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(512))

    series: Mapped[Series] = relationship(back_populates="sync_runs")
    observation_versions: Mapped[list["ObservationVersion"]] = relationship(
        back_populates="sync_run"
    )
    change_events: Mapped[list["ChangeEvent"]] = relationship(back_populates="sync_run")


class ObservationVersion(Base):
    """Append-only version of one series value for one economic period."""

    __tablename__ = "observation_versions"
    __table_args__ = (
        UniqueConstraint("content_fingerprint", name="uq_observation_versions_fingerprint"),
        CheckConstraint(
            "(is_missing AND value IS NULL) OR (NOT is_missing AND value IS NOT NULL)",
            name="missing_matches_value",
        ),
        Index(
            "ix_observation_versions_series_period_observed",
            "series_id",
            "observation_date",
            "first_observed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    series_id: Mapped[UUID] = mapped_column(
        ForeignKey("series.id", ondelete="RESTRICT"), nullable=False
    )
    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="RESTRICT"), nullable=False
    )
    observation_date: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    is_missing: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    realtime_start: Mapped[date | None] = mapped_column(Date)
    realtime_end: Mapped[date | None] = mapped_column(Date)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    content_fingerprint: Mapped[str] = mapped_column(String(64))

    series: Mapped[Series] = relationship(back_populates="observation_versions")
    sync_run: Mapped[SyncRun] = relationship(back_populates="observation_versions")


class ChangeEvent(Base):
    """Immutable meaningful change produced by a synchronization run."""

    __tablename__ = "change_events"
    __table_args__ = (
        UniqueConstraint("deterministic_key", name="uq_change_events_deterministic_key"),
        CheckConstraint(
            "change_type = 'metadata_changed' OR observation_date IS NOT NULL",
            name="observation_date_required",
        ),
        CheckConstraint(
            "absolute_change IS NULL OR absolute_change >= 0",
            name="absolute_change_nonnegative",
        ),
        Index("ix_change_events_series_occurred", "series_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    series_id: Mapped[UUID] = mapped_column(
        ForeignKey("series.id", ondelete="RESTRICT"), nullable=False
    )
    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="RESTRICT"), nullable=False
    )
    change_type: Mapped[ChangeType] = mapped_column(
        Enum(
            ChangeType,
            name="change_type",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        )
    )
    observation_date: Mapped[date | None] = mapped_column(Date)
    previous_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("observation_versions.id", ondelete="RESTRICT")
    )
    new_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("observation_versions.id", ondelete="RESTRICT")
    )
    change_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    absolute_change: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    metadata_changes: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    deterministic_key: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    series: Mapped[Series] = relationship(back_populates="change_events")
    sync_run: Mapped[SyncRun] = relationship(back_populates="change_events")
    previous_version: Mapped[ObservationVersion | None] = relationship(
        foreign_keys=[previous_version_id]
    )
    new_version: Mapped[ObservationVersion | None] = relationship(foreign_keys=[new_version_id])


class DatasetRecipe(Base):
    """Editable dataset definition whose versions are frozen for builds."""

    __tablename__ = "dataset_recipes"
    __table_args__ = (
        CheckConstraint("length(name) > 0", name="recipe_name_not_empty"),
        CheckConstraint("length(draft_hash) = 64", name="recipe_draft_hash_length"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000))
    draft_content: Mapped[dict[str, Any]] = mapped_column(JSON)
    draft_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list["RecipeVersion"]] = relationship(back_populates="recipe")
    owner: Mapped[User] = relationship(back_populates="recipes")


class RecipeVersion(Base):
    """Immutable numbered snapshot of one validated recipe draft."""

    __tablename__ = "recipe_versions"
    __table_args__ = (
        UniqueConstraint("recipe_id", "version_number", name="uq_recipe_versions_number"),
        UniqueConstraint("recipe_id", "content_hash", name="uq_recipe_versions_content"),
        CheckConstraint("version_number > 0", name="recipe_version_positive"),
        CheckConstraint("length(content_hash) = 64", name="recipe_content_hash_length"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    recipe_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_recipes.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    recipe: Mapped[DatasetRecipe] = relationship(back_populates="versions")
    variables: Mapped[list["RecipeVariable"]] = relationship(back_populates="recipe_version")
    transformation_steps: Mapped[list["TransformationStep"]] = relationship(
        back_populates="recipe_version"
    )
    build_runs: Mapped[list["BuildRun"]] = relationship(back_populates="recipe_version")


class RecipeVariable(Base):
    """One ordered provider input selected by a frozen recipe version."""

    __tablename__ = "recipe_variables"
    __table_args__ = (
        UniqueConstraint("recipe_version_id", "position", name="uq_recipe_variables_position"),
        UniqueConstraint(
            "recipe_version_id", "output_name", name="uq_recipe_variables_output_name"
        ),
        CheckConstraint("position >= 0", name="recipe_variable_position_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    recipe_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("recipe_versions.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32))
    indicator_id: Mapped[str] = mapped_column(String(128))
    output_name: Mapped[str] = mapped_column(String(128))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    recipe_version: Mapped[RecipeVersion] = relationship(back_populates="variables")


class TransformationStep(Base):
    """One ordered deterministic transformation declared by a recipe."""

    __tablename__ = "transformation_steps"
    __table_args__ = (
        UniqueConstraint("recipe_version_id", "position", name="uq_transformation_steps_position"),
        CheckConstraint("position >= 0", name="transformation_position_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    recipe_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("recipe_versions.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    recipe_version: Mapped[RecipeVersion] = relationship(back_populates="transformation_steps")


class BuildRun(Base):
    """One deterministic plan or execution of a frozen recipe version."""

    __tablename__ = "build_runs"
    __table_args__ = (
        UniqueConstraint(
            "recipe_version_id",
            "build_identity",
            "attempt_number",
            name="uq_build_runs_version_identity_attempt",
        ),
        CheckConstraint("length(build_identity) = 64", name="build_identity_length"),
        CheckConstraint("attempt_number > 0", name="build_attempt_number_positive"),
        CheckConstraint("row_count IS NULL OR row_count >= 0", name="build_row_count_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    recipe_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("recipe_versions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[BuildStatus] = mapped_column(
        Enum(
            BuildStatus,
            name="build_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=BuildStatus.PLANNED,
    )
    build_identity: Mapped[str] = mapped_column(String(64))
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    plan: Mapped[dict[str, Any]] = mapped_column(JSON)
    row_count: Mapped[int | None] = mapped_column(Integer)
    preview: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    execution_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    dataset_checksum: Mapped[str | None] = mapped_column(String(64))
    bundle_path: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(512))

    recipe_version: Mapped[RecipeVersion] = relationship(back_populates="build_runs")
    owner: Mapped[User] = relationship(back_populates="build_runs")
    inputs: Mapped[list["BuildInput"]] = relationship(back_populates="build_run")
    validation_results: Mapped[list["DatasetValidationResult"]] = relationship(
        back_populates="build_run"
    )
    lineage: Mapped["BuildLineage | None"] = relationship(back_populates="build_run")
    exports: Mapped[list["ExportArtifact"]] = relationship(back_populates="build_run")
    job: Mapped["BuildJob | None"] = relationship(back_populates="build_run")


class BuildJob(Base):
    """One durable background job for one immutable build attempt."""

    __tablename__ = "build_jobs"
    __table_args__ = (
        UniqueConstraint("build_run_id", name="uq_build_jobs_build_run_id"),
        CheckConstraint("attempt_count >= 0", name="build_job_attempt_count_nonnegative"),
        CheckConstraint("max_attempts > 0", name="build_job_max_attempts_positive"),
        Index("ix_build_jobs_claim", "status", "available_at", "created_at"),
        Index("ix_build_jobs_lease_expires_at", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    build_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("build_runs.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            name="job_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=JobStatus.QUEUED,
    )
    progress: Mapped[str] = mapped_column(String(32), default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(512))

    build_run: Mapped[BuildRun] = relationship(back_populates="job")


class BuildInput(Base):
    """Resolved provider request and metadata used to create a build plan."""

    __tablename__ = "build_inputs"
    __table_args__ = (
        UniqueConstraint("build_run_id", "output_name", name="uq_build_inputs_output_name"),
        CheckConstraint(
            "length(indicator_fingerprint) = 64", name="build_input_fingerprint_length"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    build_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("build_runs.id", ondelete="RESTRICT"), nullable=False
    )
    output_name: Mapped[str] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(32))
    indicator_id: Mapped[str] = mapped_column(String(128))
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    indicator_metadata: Mapped[dict[str, Any]] = mapped_column(JSON)
    indicator_fingerprint: Mapped[str] = mapped_column(String(64))

    build_run: Mapped[BuildRun] = relationship(back_populates="inputs")


class DatasetValidationResult(Base):
    """One persisted machine-readable validation finding."""

    __tablename__ = "validation_results"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    build_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("build_runs.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    variable: Mapped[str | None] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(String(1000))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    build_run: Mapped[BuildRun] = relationship(back_populates="validation_results")


class BuildLineage(Base):
    """Complete source-to-output column lineage for one successful build."""

    __tablename__ = "build_lineage"
    __table_args__ = (UniqueConstraint("build_run_id", name="uq_build_lineage_build"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    build_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("build_runs.id", ondelete="RESTRICT"), nullable=False
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    build_run: Mapped[BuildRun] = relationship(back_populates="lineage")


class ExportArtifact(Base):
    """Checksum-addressed generated file stored outside PostgreSQL."""

    __tablename__ = "exports"
    __table_args__ = (
        UniqueConstraint("build_run_id", "name", name="uq_exports_build_name"),
        CheckConstraint("size_bytes >= 0", name="export_size_nonnegative"),
        CheckConstraint("length(sha256) = 64", name="export_sha256_length"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    build_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("build_runs.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(64))
    relative_path: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    build_run: Mapped[BuildRun] = relationship(back_populates="exports")
