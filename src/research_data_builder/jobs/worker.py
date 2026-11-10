"""Background worker for durable build jobs."""

import asyncio
import logging
import os
import socket
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from research_data_builder.artifacts import ArtifactStorage, create_artifact_storage
from research_data_builder.audit import AuditRepository
from research_data_builder.core.config import Settings, get_settings
from research_data_builder.core.logging import configure_logging
from research_data_builder.db.build_repositories import BuildRepository
from research_data_builder.db.models import BuildRun, BuildStatus
from research_data_builder.db.session import Database
from research_data_builder.jobs.execution import BuildJobExecutionError, BuildJobExecutor
from research_data_builder.jobs.repository import (
    BuildJobRepository,
    JobCancellationRequested,
)
from research_data_builder.providers.registry import ProviderRegistry
from research_data_builder.providers.runtime import ProviderRuntime

logger = logging.getLogger(__name__)


class BuildWorker:
    """Claim and execute durable jobs for one worker process."""

    def __init__(
        self,
        database: Database,
        executor: BuildJobExecutor,
        *,
        worker_id: str,
        lease_seconds: int,
        poll_seconds: float,
    ) -> None:
        self.database = database
        self.executor = executor
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.poll_seconds = poll_seconds

    async def run_once(self) -> bool:
        async with self.database.session() as session, session.begin():
            expired = await BuildJobRepository(session).expire_leases()
            job = await BuildJobRepository(session).claim_next(self.worker_id, self.lease_seconds)
            if job is None:
                if expired:
                    logger.warning("expired worker leases", extra={"count": len(expired)})
                return False
            job_id = job.id
            build_id = job.build_run_id

        async with self.database.session() as session:
            build = await session.scalar(select(BuildRun).where(BuildRun.id == build_id))
            if build is None:
                raise LookupError("claimed build does not exist")
            owner_id = build.owner_id

        stop_heartbeat = asyncio.Event()
        cancel_requested = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat_loop(job_id, stop_heartbeat, cancel_requested)
        )

        async def progress(value: str) -> None:
            async with self.database.session() as session, session.begin():
                await BuildJobRepository(session).set_progress(job_id, self.worker_id, value)

        try:
            execution = asyncio.create_task(
                self.executor.execute(build_id, owner_id, progress=progress)
            )
            cancellation = asyncio.create_task(cancel_requested.wait())
            done, _ = await asyncio.wait(
                {execution, cancellation}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancellation in done and cancel_requested.is_set() and not execution.done():
                execution.cancel()
                with suppress(asyncio.CancelledError):
                    await execution
                raise JobCancellationRequested("the user requested build cancellation")
            cancellation.cancel()
            with suppress(asyncio.CancelledError):
                await cancellation
            await execution
        except JobCancellationRequested:
            await self._record_cancellation(job_id, owner_id)
        except BuildJobExecutionError as error:
            await self._record_expected_failure(job_id, build_id, owner_id, error)
        except Exception as error:
            await self._record_unexpected_failure(job_id, build_id, owner_id, error)
            logger.exception("background build failed", extra={"job_id": str(job_id)})
        else:
            async with self.database.session() as session, session.begin():
                await BuildJobRepository(session).succeed(job_id, self.worker_id)
                await AuditRepository(session).record(
                    owner_id, "build.succeeded", "build", build_id, actor="worker"
                )
        finally:
            stop_heartbeat.set()
            await heartbeat
        return True

    async def _record_expected_failure(
        self,
        job_id: UUID,
        build_id: UUID,
        owner_id: UUID,
        error: BuildJobExecutionError,
    ) -> None:
        async with self.database.session() as session, session.begin():
            jobs = BuildJobRepository(session)
            failed_job = await jobs.fail(
                job_id,
                self.worker_id,
                error_code=error.code,
                error_message=str(error),
            )
            await AuditRepository(session).record(
                owner_id,
                "build.failed",
                "build",
                build_id,
                actor="worker",
                details={"error_code": error.code, "retryable": error.retryable},
            )
            if not error.retryable:
                return
            builds = BuildRepository(session)
            failed_build = await builds.get(build_id, owner_id)
            if failed_build is None or failed_build.status is not BuildStatus.FAILED:
                return
            if failed_build.attempt_number >= failed_job.max_attempts:
                return
            retry = await builds.create_retry(failed_build)
            queued = await jobs.enqueue(retry)
            queued.job.max_attempts = failed_job.max_attempts
            queued.job.force_refresh = failed_job.force_refresh
            delay = min(60, 5 * (2 ** (retry.attempt_number - 2)))
            queued.job.available_at = datetime.now(UTC) + timedelta(seconds=delay)
            await AuditRepository(session).record(
                owner_id,
                "build.retry_scheduled",
                "build",
                retry.id,
                actor="worker",
                details={"source_build_id": str(build_id), "delay_seconds": delay},
            )

    async def run_forever(self) -> None:
        await self.run_until_stopped(asyncio.Event())

    async def run_until_stopped(self, stop: asyncio.Event) -> None:
        """Process jobs until the application requests a graceful stop."""
        while not stop.is_set():
            processed = await self.run_once()
            if not processed:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self.poll_seconds)

    async def _heartbeat_loop(
        self,
        job_id: UUID,
        stop: asyncio.Event,
        cancel_requested: asyncio.Event,
    ) -> None:
        interval = min(2.0, max(0.25, self.lease_seconds / 3))
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                async with self.database.session() as session, session.begin():
                    jobs = BuildJobRepository(session)
                    active = await jobs.heartbeat(job_id, self.worker_id, self.lease_seconds)
                    requested = active and await jobs.cancellation_requested(job_id, self.worker_id)
                if requested:
                    cancel_requested.set()
                    return
                if not active:
                    return

    async def _record_cancellation(self, job_id: UUID, owner_id: UUID) -> None:
        async with self.database.session() as session, session.begin():
            job = await BuildJobRepository(session).complete_cancellation(job_id, self.worker_id)
            await AuditRepository(session).record(
                owner_id,
                "build.cancelled",
                "build",
                job.build_run_id,
                actor="worker",
            )

    async def _record_unexpected_failure(
        self,
        job_id: UUID,
        build_id: UUID,
        owner_id: UUID,
        error: Exception,
    ) -> None:
        async with self.database.session() as session, session.begin():
            build = await BuildRepository(session).get(build_id, owner_id)
            if build is not None and build.status in {
                BuildStatus.RETRIEVING,
                BuildStatus.TRANSFORMING,
                BuildStatus.VALIDATING,
                BuildStatus.EXPORTING,
            }:
                await BuildRepository(session).fail(
                    build,
                    error_code="unexpected_worker_error",
                    error_message=str(error),
                )
            await BuildJobRepository(session).fail(
                job_id,
                self.worker_id,
                error_code="unexpected_worker_error",
                error_message=str(error),
            )
            await AuditRepository(session).record(
                owner_id,
                "build.failed",
                "build",
                build_id,
                actor="worker",
                details={"error_code": "unexpected_worker_error"},
            )


def create_worker(
    settings: Settings,
    database: Database,
    registry: ProviderRegistry,
    artifact_storage: ArtifactStorage,
) -> BuildWorker:
    """Create one worker with the supplied process resources."""
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"
    return BuildWorker(
        database,
        BuildJobExecutor(
            database,
            registry,
            settings,
            artifact_storage,
        ),
        worker_id=worker_id,
        lease_seconds=settings.worker_lease_seconds,
        poll_seconds=settings.worker_poll_seconds,
    )


async def run_worker(settings: Settings) -> None:
    database = Database(settings.database_url)
    runtime = ProviderRuntime(settings)
    artifact_storage = create_artifact_storage(settings)
    worker = create_worker(settings, database, runtime.registry, artifact_storage)
    try:
        await worker.run_forever()
    finally:
        await runtime.close()
        await database.dispose()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    with suppress(KeyboardInterrupt):
        asyncio.run(run_worker(settings))


if __name__ == "__main__":
    main()
