"""Tests for durable background job persistence."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from research_data_builder.db.models import BuildJob, BuildRun, BuildStatus, JobStatus
from research_data_builder.jobs.repository import BuildJobRepository, JobTransitionError


@pytest.mark.anyio
async def test_job_repository_enqueues_and_claims_one_build() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    build = BuildRun(
        id=uuid4(),
        owner_id=uuid4(),
        recipe_version_id=uuid4(),
        status=BuildStatus.PLANNED,
        build_identity="a" * 64,
        attempt_number=1,
        plan={"inputs": []},
    )
    session.scalar = AsyncMock(side_effect=[build, None])
    repository = BuildJobRepository(session)

    result = await repository.enqueue(build)

    assert result.created is True
    assert build.status is BuildStatus.QUEUED
    assert result.job.status is JobStatus.QUEUED

    job = result.job
    job.id = uuid4()
    job.attempt_count = 0
    session.scalar = AsyncMock(side_effect=[job, build])
    claimed = await repository.claim_next("worker-1", 60)

    assert claimed is job
    assert job.status is JobStatus.RUNNING
    assert job.progress == "retrieving"
    assert job.attempt_count == 1
    assert job.lease_owner == "worker-1"
    assert job.lease_expires_at is not None
    assert build.status.value == BuildStatus.RETRIEVING.value


@pytest.mark.anyio
async def test_job_repository_rejects_nonplanned_build_and_updates_owned_job() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    build = BuildRun(
        id=uuid4(),
        owner_id=uuid4(),
        recipe_version_id=uuid4(),
        status=BuildStatus.SUCCEEDED,
        build_identity="a" * 64,
        attempt_number=1,
        plan={"inputs": []},
    )
    session.scalar = AsyncMock(side_effect=[build, None])
    repository = BuildJobRepository(session)

    with pytest.raises(JobTransitionError, match="planned"):
        await repository.enqueue(build)

    job = BuildJob(
        id=uuid4(),
        build_run_id=build.id,
        status=JobStatus.RUNNING,
        progress="retrieving",
        attempt_count=1,
        max_attempts=1,
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        lease_owner="worker-1",
    )
    session.scalar = AsyncMock(side_effect=[job.id, job.id, job, job])

    assert await repository.heartbeat(job.id, "worker-1", 60) is True
    await repository.set_progress(job.id, "worker-1", "exporting")
    await repository.succeed(job.id, "worker-1")
    assert job.status is JobStatus.SUCCEEDED
    assert job.progress == "succeeded"

    job.status = JobStatus.RUNNING
    job.lease_owner = "worker-1"
    await repository.fail(
        job.id,
        "worker-1",
        error_code="execution_failed",
        error_message="x" * 600,
    )
    assert job.status is JobStatus.FAILED
    assert len(job.error_message or "") == 512


@pytest.mark.anyio
async def test_job_repository_expires_abandoned_worker_lease() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
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
        progress="retrieving",
        attempt_count=1,
        max_attempts=1,
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        lease_owner="dead-worker",
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    rows = MagicMock()
    rows.__iter__.return_value = iter([job])
    session.scalars = AsyncMock(return_value=rows)
    session.scalar = AsyncMock(return_value=build)

    expired = await BuildJobRepository(session).expire_leases()

    assert expired == [job]
    assert job.status is JobStatus.FAILED
    assert job.error_code == "worker_lease_expired"
    assert build.status is BuildStatus.FAILED
    assert build.error_code == "worker_lease_expired"
