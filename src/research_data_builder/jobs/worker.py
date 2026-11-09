"""Background worker for durable build jobs."""

import asyncio
import logging
import os
import socket
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from research_data_builder.core.config import Settings, get_settings
from research_data_builder.core.logging import configure_logging
from research_data_builder.db.build_repositories import BuildRepository
from research_data_builder.db.models import BuildRun, BuildStatus
from research_data_builder.db.session import Database
from research_data_builder.jobs.execution import BuildJobExecutionError, BuildJobExecutor
from research_data_builder.jobs.repository import BuildJobRepository
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
        heartbeat = asyncio.create_task(self._heartbeat_loop(job_id, stop_heartbeat))

        async def progress(value: str) -> None:
            async with self.database.session() as session, session.begin():
                await BuildJobRepository(session).set_progress(job_id, self.worker_id, value)

        try:
            await self.executor.execute(build_id, owner_id, progress=progress)
        except BuildJobExecutionError as error:
            await self._record_expected_failure(job_id, build_id, owner_id, error)
        except Exception as error:
            await self._record_unexpected_failure(job_id, build_id, owner_id, error)
            logger.exception("background build failed", extra={"job_id": str(job_id)})
        else:
            async with self.database.session() as session, session.begin():
                await BuildJobRepository(session).succeed(job_id, self.worker_id)
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
            delay = min(60, 5 * (2 ** (retry.attempt_number - 2)))
            queued.job.available_at = datetime.now(UTC) + timedelta(seconds=delay)

    async def run_forever(self) -> None:
        while True:
            processed = await self.run_once()
            if not processed:
                await asyncio.sleep(self.poll_seconds)

    async def _heartbeat_loop(self, job_id: UUID, stop: asyncio.Event) -> None:
        interval = max(1.0, self.lease_seconds / 3)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                async with self.database.session() as session, session.begin():
                    active = await BuildJobRepository(session).heartbeat(
                        job_id,
                        self.worker_id,
                        self.lease_seconds,
                    )
                if not active:
                    return

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


async def run_worker(settings: Settings) -> None:
    database = Database(settings.database_url)
    runtime = ProviderRuntime(settings)
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"
    worker = BuildWorker(
        database,
        BuildJobExecutor(database, runtime.registry, settings),
        worker_id=worker_id,
        lease_seconds=settings.worker_lease_seconds,
        poll_seconds=settings.worker_poll_seconds,
    )
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
