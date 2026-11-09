"""Tests for build work outside the API request."""

from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from research_data_builder.core.config import Settings
from research_data_builder.db.models import BuildRun, BuildStatus
from research_data_builder.db.session import Database
from research_data_builder.jobs.execution import BuildJobExecutionError, BuildJobExecutor
from research_data_builder.providers import ProviderConnector, ProviderRegistry
from tests.engine.test_executor import ObservationConnector, version_and_plan
from tests.recipes.test_api_behavior import FakeApiDatabase, session_with


@pytest.mark.anyio
async def test_job_executor_completes_claimed_build(tmp_path: Path) -> None:
    version, plan = version_and_plan()
    owner_id = uuid4()
    build = BuildRun(
        id=uuid4(),
        owner_id=owner_id,
        recipe_version_id=version.id,
        status=BuildStatus.RETRIEVING,
        build_identity=plan.build_identity,
        attempt_number=1,
        plan=plan.as_dict(),
    )
    database = FakeApiDatabase(
        session_with(build, version),
        session_with(build),
    )
    registry = ProviderRegistry([cast(ProviderConnector, ObservationConnector())])
    progress = AsyncMock()
    executor = BuildJobExecutor(
        cast(Database, database),
        registry,
        Settings(artifact_root=tmp_path, _env_file=None),  # type: ignore[call-arg]
    )

    result = await executor.execute(build.id, owner_id, progress=progress, preview_limit=1)

    assert result.status is BuildStatus.SUCCEEDED
    assert result.dataset_checksum is not None
    assert result.row_count == 2
    assert result.preview is not None
    assert result.preview["truncated"] is True
    assert [call.args[0] for call in progress.await_args_list] == [
        "retrieving",
        "validating",
        "exporting",
    ]


@pytest.mark.anyio
async def test_job_executor_records_provider_failure(tmp_path: Path) -> None:
    version, plan = version_and_plan()
    owner_id = uuid4()
    build = BuildRun(
        id=uuid4(),
        owner_id=owner_id,
        recipe_version_id=version.id,
        status=BuildStatus.RETRIEVING,
        build_identity=plan.build_identity,
        attempt_number=1,
        plan=plan.as_dict(),
    )
    database = FakeApiDatabase(
        session_with(build, version),
        session_with(build),
    )
    executor = BuildJobExecutor(
        cast(Database, database),
        ProviderRegistry([]),
        Settings(artifact_root=tmp_path, _env_file=None),  # type: ignore[call-arg]
    )

    with pytest.raises(BuildJobExecutionError) as failure:
        await executor.execute(build.id, owner_id, progress=AsyncMock())

    assert failure.value.code == "execution_failed"
    assert build.status is BuildStatus.FAILED
    assert build.error_code == "execution_failed"
