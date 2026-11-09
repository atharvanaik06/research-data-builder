"""Persistence for deterministic build plans and resolved provider inputs."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from research_data_builder.db.models import BuildInput, BuildRun, BuildStatus
from research_data_builder.engine.result import ExecutionResult
from research_data_builder.recipes.planner import BuildPlan


@dataclass(frozen=True, slots=True)
class PlannedBuildResult:
    """A planned build plus whether it was newly persisted."""

    build: BuildRun
    created: bool


class BuildTransitionError(ValueError):
    """A build cannot move from its current state to the requested state."""

    def __init__(self, current: BuildStatus, requested: BuildStatus) -> None:
        self.current = current
        self.requested = requested
        super().__init__(f"build cannot transition from {current.value} to {requested.value}")


class BuildRepository:
    """Create or reuse deterministic build plans without committing transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_or_get(
        self,
        owner_id: UUID,
        recipe_version_id: UUID,
        plan: BuildPlan,
    ) -> PlannedBuildResult:
        existing = await self.get_by_identity(owner_id, recipe_version_id, plan.build_identity)
        if existing is not None:
            return PlannedBuildResult(build=existing, created=False)

        build = BuildRun(
            owner_id=owner_id,
            recipe_version_id=recipe_version_id,
            status=BuildStatus.PLANNED,
            build_identity=plan.build_identity,
            attempt_number=1,
            plan=plan.as_dict(),
        )
        self.session.add(build)
        await self.session.flush()
        for item in plan.inputs:
            self.session.add(
                BuildInput(
                    build_run_id=build.id,
                    output_name=item.output_name,
                    provider=item.provider,
                    indicator_id=item.indicator_id,
                    request=item.request,
                    indicator_metadata=item.indicator_metadata,
                    indicator_fingerprint=item.indicator_fingerprint,
                )
            )
        await self.session.flush()
        return PlannedBuildResult(build=build, created=True)

    async def get(self, build_id: UUID, owner_id: UUID) -> BuildRun | None:
        return await self.session.scalar(
            select(BuildRun).where(BuildRun.id == build_id, BuildRun.owner_id == owner_id)
        )

    async def get_by_identity(
        self,
        owner_id: UUID,
        recipe_version_id: UUID,
        build_identity: str,
    ) -> BuildRun | None:
        return await self.session.scalar(
            select(BuildRun)
            .where(
                BuildRun.owner_id == owner_id,
                BuildRun.recipe_version_id == recipe_version_id,
                BuildRun.build_identity == build_identity,
            )
            .order_by(BuildRun.attempt_number.desc())
        )

    async def claim_execution(self, build_id: UUID, owner_id: UUID) -> BuildRun:
        """Atomically move one planned build to retrieving."""
        claimed = await self.session.scalar(
            update(BuildRun)
            .where(
                BuildRun.id == build_id,
                BuildRun.owner_id == owner_id,
                BuildRun.status == BuildStatus.PLANNED,
            )
            .values(
                status=BuildStatus.RETRIEVING,
                started_at=datetime.now(UTC),
                finished_at=None,
                error_code=None,
                error_message=None,
            )
            .returning(BuildRun)
        )
        if claimed is not None:
            claimed.status = BuildStatus.RETRIEVING
            return claimed
        current = await self.get(build_id, owner_id)
        if current is None:
            raise LookupError("build not found")
        raise BuildTransitionError(current.status, BuildStatus.RETRIEVING)

    async def create_retry(self, build: BuildRun) -> BuildRun:
        """Create a new planned row for one failed attempt without mutating history."""
        self._require_status(build, BuildStatus.FAILED, BuildStatus.PLANNED)
        latest_attempt = await self.session.scalar(
            select(func.max(BuildRun.attempt_number)).where(
                BuildRun.owner_id == build.owner_id,
                BuildRun.recipe_version_id == build.recipe_version_id,
                BuildRun.build_identity == build.build_identity,
            )
        )
        retry = BuildRun(
            owner_id=build.owner_id,
            recipe_version_id=build.recipe_version_id,
            status=BuildStatus.PLANNED,
            build_identity=build.build_identity,
            attempt_number=(latest_attempt or build.attempt_number) + 1,
            plan=build.plan,
        )
        self.session.add(retry)
        await self.session.flush()
        inputs = await self.session.scalars(
            select(BuildInput)
            .where(BuildInput.build_run_id == build.id)
            .order_by(BuildInput.output_name)
        )
        for item in inputs:
            self.session.add(
                BuildInput(
                    build_run_id=retry.id,
                    output_name=item.output_name,
                    provider=item.provider,
                    indicator_id=item.indicator_id,
                    request=item.request,
                    indicator_metadata=item.indicator_metadata,
                    indicator_fingerprint=item.indicator_fingerprint,
                )
            )
        await self.session.flush()
        return retry

    async def record_execution(
        self,
        build: BuildRun,
        result: ExecutionResult,
        *,
        preview_limit: int,
    ) -> BuildRun:
        self._require_status(build, BuildStatus.RETRIEVING, BuildStatus.VALIDATING)
        preview = result.preview(limit=preview_limit)
        build.status = BuildStatus.VALIDATING
        build.row_count = result.frame.height
        build.preview = preview.as_dict()
        build.execution_summary = {
            "entity_mapping_version": result.entity_mapping_version,
            "join_reports": [asdict(report) for report in result.join_reports],
        }
        await self.session.flush()
        return build

    async def fail(self, build: BuildRun, *, error_code: str, error_message: str) -> BuildRun:
        if build.status not in {
            BuildStatus.RETRIEVING,
            BuildStatus.TRANSFORMING,
            BuildStatus.VALIDATING,
            BuildStatus.EXPORTING,
        }:
            raise BuildTransitionError(build.status, BuildStatus.FAILED)
        build.status = BuildStatus.FAILED
        build.finished_at = datetime.now(UTC)
        build.error_code = error_code
        build.error_message = error_message[:512]
        await self.session.flush()
        return build

    @staticmethod
    def _require_status(
        build: BuildRun,
        expected: BuildStatus,
        requested: BuildStatus,
    ) -> None:
        if build.status is not expected:
            raise BuildTransitionError(build.status, requested)
