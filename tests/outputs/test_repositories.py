"""Tests for strict successful-build persistence."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from research_data_builder.artifacts.models import BundleResult, ExportedArtifact
from research_data_builder.db.build_repositories import BuildTransitionError
from research_data_builder.db.models import (
    BuildRun,
    BuildStatus,
    DatasetValidationResult,
    ExportArtifact,
)
from research_data_builder.db.output_repositories import BuildOutputRepository
from research_data_builder.validation.models import ValidationIssue, ValidationReport


def artifact(name: str) -> ExportedArtifact:
    return ExportedArtifact(name, "test", f"builds/id/{name}", 1, "a" * 64)


def passing_report() -> ValidationReport:
    return ValidationReport(
        passed=True,
        row_count=1,
        expected_row_count=1,
        coverage_percent=100.0,
        issues=(ValidationIssue("validation_passed", "info", "passed"),),
        missing_by_variable={"value": 0},
    )


def failing_report() -> ValidationReport:
    return ValidationReport(
        passed=False,
        row_count=1,
        expected_row_count=1,
        coverage_percent=100.0,
        issues=(ValidationIssue("range_violation", "error", "outside range", "value"),),
        missing_by_variable={"value": 0},
    )


@pytest.mark.anyio
async def test_output_repository_requires_complete_bundle_before_success() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    repository = BuildOutputRepository(session)
    build = MagicMock(spec=BuildRun)
    build.id = uuid4()
    build.status = BuildStatus.VALIDATING
    names = sorted(repository.REQUIRED_DOCUMENTS | {"data.csv", "data.parquet"})
    bundle = BundleResult(
        directory=Path("/tmp/build"),
        dataset_checksum="b" * 64,
        artifacts=tuple(artifact(name) for name in names),
        manifest={},
        lineage={"columns": []},
    )

    await repository.record_success(build, bundle, passing_report())

    assert build.status is BuildStatus.SUCCEEDED
    assert build.dataset_checksum == "b" * 64
    assert session.execute.await_count == 0
    added = [call.args[0] for call in session.add.call_args_list]
    assert any(isinstance(item, DatasetValidationResult) for item in added)
    assert sum(isinstance(item, ExportArtifact) for item in added) == len(names)

    incomplete_build = MagicMock(spec=BuildRun)
    incomplete_build.status = BuildStatus.VALIDATING
    incomplete = BundleResult(Path("/tmp"), "c" * 64, (), {}, {})
    with pytest.raises(ValueError, match="missing"):
        await repository.record_success(incomplete_build, incomplete, passing_report())

    with pytest.raises(BuildTransitionError, match="succeeded to succeeded"):
        await repository.record_success(build, bundle, passing_report())


@pytest.mark.anyio
async def test_output_repository_persists_blocking_validation_failure() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    repository = BuildOutputRepository(session)
    build = MagicMock(spec=BuildRun)
    build.id = uuid4()
    build.status = BuildStatus.VALIDATING

    await repository.record_validation_failure(build, failing_report())

    assert build.status is BuildStatus.FAILED
    assert build.error_code == "validation_failed"
    assert session.execute.await_count == 0

    passing_build = MagicMock(spec=BuildRun)
    passing_build.status = BuildStatus.VALIDATING
    with pytest.raises(ValueError, match="blocking error"):
        await repository.record_validation_failure(passing_build, passing_report())
