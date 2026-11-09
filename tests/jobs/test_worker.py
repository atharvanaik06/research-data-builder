"""Tests for the independent background worker process."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from research_data_builder.db.models import BuildJob, BuildRun, BuildStatus, JobStatus
from research_data_builder.db.session import Database
from research_data_builder.jobs.execution import BuildJobExecutionError, BuildJobExecutor
from research_data_builder.jobs.worker import BuildWorker
from tests.recipes.test_api_behavior import FakeApiDatabase, session_with


@pytest.mark.anyio
async def test_worker_returns_when_queue_is_empty() -> None:
    session = session_with(None)
    no_expired = MagicMock()
    no_expired.__iter__.return_value = iter([])
    session.scalars.return_value = no_expired
    database = FakeApiDatabase(session)
    executor = MagicMock(spec=BuildJobExecutor)
    worker = BuildWorker(
        cast(Database, database),
        executor,
        worker_id="worker-1",
        lease_seconds=60,
        poll_seconds=0.01,
    )

    assert await worker.run_once() is False
    executor.execute.assert_not_called()


@pytest.mark.anyio
async def test_worker_claims_executes_and_completes_job() -> None:
    build = BuildRun(
        id=uuid4(),
        owner_id=uuid4(),
        recipe_version_id=uuid4(),
        status=BuildStatus.QUEUED,
        build_identity="a" * 64,
        attempt_number=1,
        plan={"inputs": []},
    )
    job = BuildJob(
        id=uuid4(),
        build_run_id=build.id,
        status=JobStatus.QUEUED,
        progress="queued",
        attempt_count=0,
        max_attempts=1,
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    claim_session = session_with(job, build)
    no_expired = MagicMock()
    no_expired.__iter__.return_value = iter([])
    claim_session.scalars.return_value = no_expired
    fetch_session = session_with(build)
    finish_session = session_with(job)
    database = FakeApiDatabase(claim_session, fetch_session, finish_session)
    executor = MagicMock(spec=BuildJobExecutor)
    executor.execute = AsyncMock(return_value=build)
    worker = BuildWorker(
        cast(Database, database),
        executor,
        worker_id="worker-1",
        lease_seconds=60,
        poll_seconds=0.01,
    )

    processed = await worker.run_once()

    assert processed is True
    assert build.status is BuildStatus.RETRIEVING
    assert job.status is JobStatus.SUCCEEDED
    assert job.progress == "succeeded"
    executor.execute.assert_awaited_once()


@pytest.mark.anyio
async def test_worker_records_expected_build_failure() -> None:
    build = BuildRun(
        id=uuid4(),
        owner_id=uuid4(),
        recipe_version_id=uuid4(),
        status=BuildStatus.QUEUED,
        build_identity="a" * 64,
        attempt_number=1,
        plan={"inputs": []},
    )
    job = BuildJob(
        id=uuid4(),
        build_run_id=build.id,
        status=JobStatus.QUEUED,
        progress="queued",
        attempt_count=0,
        max_attempts=1,
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    claim_session = session_with(job, build)
    no_expired = MagicMock()
    no_expired.__iter__.return_value = iter([])
    claim_session.scalars.return_value = no_expired
    database = FakeApiDatabase(
        claim_session,
        session_with(build),
        session_with(job),
    )
    executor = MagicMock(spec=BuildJobExecutor)
    executor.execute = AsyncMock(
        side_effect=BuildJobExecutionError("validation_failed", "validation failed")
    )
    worker = BuildWorker(
        cast(Database, database),
        executor,
        worker_id="worker-1",
        lease_seconds=60,
        poll_seconds=0.01,
    )

    assert await worker.run_once() is True
    assert job.status is JobStatus.FAILED
    assert job.error_code == "validation_failed"
