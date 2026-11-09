"""PostgreSQL queue operations for background build jobs."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from research_data_builder.db.models import BuildJob, BuildRun, BuildStatus, JobStatus


class JobTransitionError(ValueError):
    """A job or build cannot move to the requested state."""


class JobCancellationRequested(RuntimeError):
    """The user requested cancellation of a running job."""


class UserBuildLimitError(ValueError):
    """The user has too many queued or running builds."""


@dataclass(frozen=True, slots=True)
class EnqueuedJobResult:
    """A queued job and its creation status."""

    job: BuildJob
    created: bool


class BuildJobRepository:
    """Create, claim, update, and finish durable build jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        build: BuildRun,
        *,
        force_refresh: bool = False,
        max_outstanding: int | None = None,
    ) -> EnqueuedJobResult:
        locked_build = await self.session.scalar(
            select(BuildRun).where(BuildRun.id == build.id).with_for_update()
        )
        if locked_build is None:
            raise LookupError("build does not exist")
        build = locked_build
        existing = await self.get_for_build(build.id, build.owner_id)
        if existing is not None:
            return EnqueuedJobResult(existing, False)
        if build.status is not BuildStatus.PLANNED:
            raise JobTransitionError(f"build status must be planned, not {build.status.value}")
        if max_outstanding is not None:
            outstanding = await self.count_outstanding(build.owner_id)
            if outstanding >= max_outstanding:
                raise UserBuildLimitError(
                    f"user has {outstanding} queued or running builds; limit is {max_outstanding}"
                )
        build.status = BuildStatus.QUEUED
        job = BuildJob(
            build_run_id=build.id,
            status=JobStatus.QUEUED,
            progress="queued",
            attempt_count=0,
            max_attempts=3,
            force_refresh=force_refresh,
            available_at=datetime.now(UTC),
        )
        self.session.add(job)
        await self.session.flush()
        return EnqueuedJobResult(job, True)

    async def count_outstanding(self, owner_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count(BuildJob.id))
            .join(BuildRun, BuildRun.id == BuildJob.build_run_id)
            .where(
                BuildRun.owner_id == owner_id,
                BuildJob.status.in_({JobStatus.QUEUED, JobStatus.RUNNING}),
            )
        )
        return int(count or 0)

    async def get(self, job_id: UUID) -> BuildJob | None:
        return await self.session.scalar(select(BuildJob).where(BuildJob.id == job_id))

    async def get_for_build(self, build_id: UUID, owner_id: UUID) -> BuildJob | None:
        return await self.session.scalar(
            select(BuildJob)
            .join(BuildRun, BuildRun.id == BuildJob.build_run_id)
            .where(BuildJob.build_run_id == build_id, BuildRun.owner_id == owner_id)
        )

    async def claim_next(self, worker_id: str, lease_seconds: int) -> BuildJob | None:
        now = datetime.now(UTC)
        job = await self.session.scalar(
            select(BuildJob)
            .where(
                BuildJob.status == JobStatus.QUEUED,
                BuildJob.available_at <= now,
            )
            .order_by(BuildJob.available_at, BuildJob.created_at, BuildJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        build = await self.session.scalar(
            select(BuildRun).where(BuildRun.id == job.build_run_id).with_for_update()
        )
        if build is None:
            raise LookupError("queued build does not exist")
        if build.status is not BuildStatus.QUEUED:
            raise JobTransitionError(f"queued job requires queued build, not {build.status.value}")
        job.status = JobStatus.RUNNING
        job.progress = "retrieving"
        job.attempt_count += 1
        job.lease_owner = worker_id
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.started_at = job.started_at or now
        job.finished_at = None
        job.error_code = None
        job.error_message = None
        build.status = BuildStatus.RETRIEVING
        build.started_at = build.started_at or now
        await self.session.flush()
        return job

    async def heartbeat(self, job_id: UUID, worker_id: str, lease_seconds: int) -> bool:
        now = datetime.now(UTC)
        updated_id = await self.session.scalar(
            update(BuildJob)
            .where(
                BuildJob.id == job_id,
                BuildJob.status == JobStatus.RUNNING,
                BuildJob.lease_owner == worker_id,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
            .returning(BuildJob.id)
        )
        return updated_id is not None

    async def cancellation_requested(self, job_id: UUID, worker_id: str) -> bool:
        requested_at = await self.session.scalar(
            select(BuildJob.cancel_requested_at).where(
                BuildJob.id == job_id,
                BuildJob.status == JobStatus.RUNNING,
                BuildJob.lease_owner == worker_id,
            )
        )
        return requested_at is not None

    async def ensure_not_cancelled_for_build(self, build_id: UUID) -> None:
        job = await self.session.scalar(
            select(BuildJob).where(BuildJob.build_run_id == build_id).with_for_update()
        )
        if job is not None and job.cancel_requested_at is not None:
            raise JobCancellationRequested("the user requested build cancellation")

    async def set_progress(self, job_id: UUID, worker_id: str, progress: str) -> None:
        updated_id = await self.session.scalar(
            update(BuildJob)
            .where(
                BuildJob.id == job_id,
                BuildJob.status == JobStatus.RUNNING,
                BuildJob.lease_owner == worker_id,
                BuildJob.cancel_requested_at.is_(None),
            )
            .values(progress=progress)
            .returning(BuildJob.id)
        )
        if updated_id is None:
            if await self.cancellation_requested(job_id, worker_id):
                raise JobCancellationRequested("the user requested build cancellation")
            raise JobTransitionError("worker does not own the running job")

    async def request_cancel(self, build_id: UUID, owner_id: UUID) -> BuildJob:
        job = await self.session.scalar(
            select(BuildJob)
            .join(BuildRun, BuildRun.id == BuildJob.build_run_id)
            .where(BuildJob.build_run_id == build_id, BuildRun.owner_id == owner_id)
            .with_for_update()
        )
        if job is None:
            raise LookupError("job does not exist")
        build = await self.session.scalar(
            select(BuildRun).where(BuildRun.id == build_id).with_for_update()
        )
        if build is None:
            raise LookupError("build does not exist")
        if job.status is JobStatus.CANCELLED:
            return job
        if job.status is JobStatus.QUEUED and build.status is BuildStatus.QUEUED:
            self._mark_cancelled(job, build)
        elif job.status is JobStatus.RUNNING and build.status in self._active_build_statuses():
            job.cancel_requested_at = job.cancel_requested_at or datetime.now(UTC)
            job.progress = "cancelling"
        else:
            raise JobTransitionError(
                f"job status must be queued or running, not {job.status.value}"
            )
        await self.session.flush()
        return job

    async def complete_cancellation(self, job_id: UUID, worker_id: str) -> BuildJob:
        job = await self.session.scalar(
            select(BuildJob)
            .where(
                BuildJob.id == job_id,
                BuildJob.status == JobStatus.RUNNING,
                BuildJob.lease_owner == worker_id,
                BuildJob.cancel_requested_at.is_not(None),
            )
            .with_for_update()
        )
        if job is None:
            raise JobTransitionError("worker does not own the cancelled job")
        build = await self.session.scalar(
            select(BuildRun).where(BuildRun.id == job.build_run_id).with_for_update()
        )
        if build is None:
            raise LookupError("build does not exist")
        if build.status not in self._active_build_statuses():
            raise JobTransitionError(f"build cannot be cancelled from {build.status.value}")
        self._mark_cancelled(job, build)
        await self.session.flush()
        return job

    async def succeed(self, job_id: UUID, worker_id: str) -> BuildJob:
        job = await self._owned_running_job(job_id, worker_id)
        job.status = JobStatus.SUCCEEDED
        job.progress = "succeeded"
        job.finished_at = datetime.now(UTC)
        job.lease_owner = None
        job.lease_expires_at = None
        await self.session.flush()
        return job

    async def fail(
        self,
        job_id: UUID,
        worker_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> BuildJob:
        job = await self._owned_running_job(job_id, worker_id)
        job.status = JobStatus.FAILED
        job.progress = "failed"
        job.finished_at = datetime.now(UTC)
        job.error_code = error_code
        job.error_message = error_message[:512]
        job.lease_owner = None
        job.lease_expires_at = None
        await self.session.flush()
        return job

    async def expire_leases(self) -> list[BuildJob]:
        now = datetime.now(UTC)
        rows = await self.session.scalars(
            select(BuildJob)
            .where(
                BuildJob.status == JobStatus.RUNNING,
                BuildJob.lease_expires_at < now,
            )
            .with_for_update(skip_locked=True)
        )
        expired = list(rows)
        for job in expired:
            build = await self.session.scalar(
                select(BuildRun).where(BuildRun.id == job.build_run_id).with_for_update()
            )
            if build is not None and build.status in {
                BuildStatus.RETRIEVING,
                BuildStatus.TRANSFORMING,
                BuildStatus.VALIDATING,
                BuildStatus.EXPORTING,
            }:
                build.status = BuildStatus.FAILED
                build.finished_at = now
                build.error_code = "worker_lease_expired"
                build.error_message = "the worker lease expired before job completion"
            job.status = JobStatus.FAILED
            job.progress = "failed"
            job.finished_at = now
            job.error_code = "worker_lease_expired"
            job.error_message = "the worker lease expired before job completion"
            job.lease_owner = None
            job.lease_expires_at = None
        await self.session.flush()
        return expired

    async def _owned_running_job(self, job_id: UUID, worker_id: str) -> BuildJob:
        job = await self.session.scalar(
            select(BuildJob)
            .where(
                BuildJob.id == job_id,
                BuildJob.status == JobStatus.RUNNING,
                BuildJob.lease_owner == worker_id,
            )
            .with_for_update()
        )
        if job is None:
            raise JobTransitionError("worker does not own the running job")
        return job

    @staticmethod
    def _active_build_statuses() -> set[BuildStatus]:
        return {
            BuildStatus.RETRIEVING,
            BuildStatus.TRANSFORMING,
            BuildStatus.VALIDATING,
            BuildStatus.EXPORTING,
        }

    @staticmethod
    def _mark_cancelled(job: BuildJob, build: BuildRun) -> None:
        now = datetime.now(UTC)
        job.status = JobStatus.CANCELLED
        job.progress = "cancelled"
        job.finished_at = now
        job.error_code = "cancelled_by_user"
        job.error_message = "the user cancelled this build"
        job.lease_owner = None
        job.lease_expires_at = None
        build.status = BuildStatus.CANCELLED
        build.finished_at = now
        build.error_code = "cancelled_by_user"
        build.error_message = "the user cancelled this build"
