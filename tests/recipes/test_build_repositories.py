"""Tests for idempotent build-plan persistence."""

from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import polars as pl
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from research_data_builder.db.build_repositories import BuildRepository
from research_data_builder.db.models import BuildInput, BuildStatus
from research_data_builder.engine import ExecutionResult, JoinReport
from research_data_builder.recipes.planner import BuildPlan, ResolvedBuildInput


def build_plan() -> BuildPlan:
    item = ResolvedBuildInput(
        output_name="gdp_growth",
        provider="world_bank",
        indicator_id="NY.GDP.MKTP.KD.ZG",
        request={"entity_ids": ["CZE"]},
        indicator_metadata={"title": "GDP growth"},
        indicator_fingerprint="a" * 64,
    )
    return BuildPlan(
        recipe_version_id=str(uuid4()),
        recipe_content_hash="b" * 64,
        build_identity="c" * 64,
        planner_version="1",
        inputs=(item,),
    )


@pytest.mark.anyio
async def test_build_repository_persists_plan_and_resolved_inputs() -> None:
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    repository = BuildRepository(session)
    owner_id = uuid4()
    version_id = uuid4()

    result = await repository.create_or_get(owner_id, version_id, build_plan())

    assert result.created is True
    assert result.build.owner_id == owner_id
    assert result.build.status is BuildStatus.PLANNED
    added = [call.args[0] for call in session.add.call_args_list]
    inputs = [item for item in added if isinstance(item, BuildInput)]
    assert inputs[0].output_name == "gdp_growth"
    assert session.flush.await_count == 2


@pytest.mark.anyio
async def test_build_repository_reuses_existing_identity() -> None:
    session = MagicMock(spec=AsyncSession)
    existing = MagicMock()
    session.scalar = AsyncMock(return_value=existing)
    session.flush = AsyncMock()

    result = await BuildRepository(session).create_or_get(uuid4(), uuid4(), build_plan())

    assert result.created is False
    assert result.build is existing
    session.add.assert_not_called()


@pytest.mark.anyio
async def test_build_repository_records_execution_and_failure_states() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    repository = BuildRepository(session)
    build = MagicMock()
    build.started_at = None

    await repository.mark_retrieving(build)
    assert build.status is BuildStatus.RETRIEVING
    assert build.started_at is not None

    result = ExecutionResult(
        frame=pl.DataFrame({"entity": ["CZE"], "value": [1]}),
        join_reports=(JoinReport("inflation", 1, 0),),
        entity_mapping_version="v1",
    )
    await repository.record_execution(build, result, preview_limit=10)
    assert cast(BuildStatus, build.status) is BuildStatus.VALIDATING
    assert build.row_count == 1
    assert build.preview["total_row_count"] == 1
    assert build.execution_summary["join_reports"][0]["left_only_keys"] == 1

    await repository.fail(build, error_code="execution_failed", error_message="x" * 600)
    assert cast(BuildStatus, build.status) is BuildStatus.FAILED
    assert len(build.error_message) == 512
