"""Tests for the independent background worker process."""

import asyncio
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
async def test_worker_loop_stops_during_empty_poll() -> None:
    session = session_with(None)
    no_expired = MagicMock()
    no_expired.__iter__.return_value = iter([])
    session.scalars.return_value = no_expired
    worker = BuildWorker(
        cast(Database, FakeApiDatabase(session)),
        MagicMock(spec=BuildJobExecutor),
        worker_id="embedded-worker",
        lease_seconds=60,
        poll_seconds=60,
    )
    stop = asyncio.Event()

    task = asyncio.create_task(worker.run_until_stopped(stop))
    await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=1)


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


@pytest.mark.anyio
async def test_worker_schedules_new_build_for_retryable_failure() -> None:
    build = BuildRun(
        id=uuid4(),
        owner_id=uuid4(),
        recipe_version_id=uuid4(),
        status=BuildStatus.FAILED,
        build_identity="a" * 64,
        attempt_number=1,
        plan={"inputs": []},
    )
    job = BuildJob(
        id=uuid4(),
        build_run_id=build.id,
        status=JobStatus.RUNNING,
        progress="retrieving",
        attempt_count=1,
        max_attempts=3,
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        lease_owner="worker-1",
    )
    session = session_with()
    scalar_calls = 0

    async def scalar_result(_: object) -> object:
        nonlocal scalar_calls
        scalar_calls += 1
        if scalar_calls == 1:
            return job
        if scalar_calls == 2:
            return build
        if scalar_calls == 3:
            return 1
        if scalar_calls == 4:
            return next(
                call.args[0]
                for call in session.add.call_args_list
                if isinstance(call.args[0], BuildRun)
            )
        return None

    session.scalar = AsyncMock(side_effect=scalar_result)
    no_inputs = MagicMock()
    no_inputs.__iter__.return_value = iter([])
    session.scalars.return_value = no_inputs
    database = FakeApiDatabase(session)
    worker = BuildWorker(
        cast(Database, database),
        MagicMock(spec=BuildJobExecutor),
        worker_id="worker-1",
        lease_seconds=60,
        poll_seconds=0.01,
    )

    await worker._record_expected_failure(
        job.id,
        build.id,
        build.owner_id,
        BuildJobExecutionError("execution_failed", "timeout", retryable=True),
    )

    retries = [
        call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], BuildRun)
    ]
    queued_jobs = [
        call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], BuildJob)
    ]
    assert job.status is JobStatus.FAILED
    assert retries[0].attempt_number == 2
    assert retries[0].status is BuildStatus.QUEUED
    assert queued_jobs[0].max_attempts == 3
    assert queued_jobs[0].available_at > datetime.now(UTC)


@pytest.mark.anyio
async def test_worker_completes_requested_cancellation() -> None:
    build = BuildRun(
        id=uuid4(),
        owner_id=uuid4(),
        recipe_version_id=uuid4(),
        status=BuildStatus.RETRIEVING,
        build_identity="a" * 64,
        attempt_number=1,
        plan={"inputs": []},
    )
    job = BuildJob(
        id=uuid4(),
        build_run_id=build.id,
        status=JobStatus.RUNNING,
        progress="cancelling",
        attempt_count=1,
        max_attempts=3,
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        lease_owner="worker-1",
        cancel_requested_at=datetime.now(UTC),
    )
    worker = BuildWorker(
        cast(Database, FakeApiDatabase(session_with(job, build))),
        MagicMock(spec=BuildJobExecutor),
        worker_id="worker-1",
        lease_seconds=60,
        poll_seconds=0.01,
    )

    await worker._record_cancellation(job.id, build.owner_id)

    assert job.status is JobStatus.CANCELLED
    assert job.progress == "cancelled"
    assert build.status is BuildStatus.CANCELLED


@pytest.mark.anyio
async def test_worker_stops_execution_when_heartbeat_finds_cancellation() -> None:
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
        max_attempts=3,
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    claim_session = session_with(job, build)
    no_expired = MagicMock()
    no_expired.__iter__.return_value = iter([])
    claim_session.scalars.return_value = no_expired
    heartbeat_session = session_with(job.id, datetime.now(UTC))
    database = FakeApiDatabase(
        claim_session,
        session_with(build),
        heartbeat_session,
        session_with(job, build),
    )
    executor = MagicMock(spec=BuildJobExecutor)

    async def wait_until_cancelled(*_: object, **__: object) -> None:
        await asyncio.Event().wait()

    executor.execute = AsyncMock(side_effect=wait_until_cancelled)
    worker = BuildWorker(
        cast(Database, database),
        executor,
        worker_id="worker-1",
        lease_seconds=0,
        poll_seconds=0.01,
    )

    assert await worker.run_once() is True
    assert job.status is JobStatus.CANCELLED
    assert build.status.value == BuildStatus.CANCELLED.value
