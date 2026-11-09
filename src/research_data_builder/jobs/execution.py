"""Execute one build that a background worker already claimed."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from research_data_builder.artifacts import export_research_bundle
from research_data_builder.core.config import Settings
from research_data_builder.db.build_repositories import BuildRepository
from research_data_builder.db.models import BuildRun, BuildStatus
from research_data_builder.db.output_repositories import BuildOutputRepository
from research_data_builder.db.recipe_repositories import RecipeVersionRepository
from research_data_builder.db.session import Database
from research_data_builder.engine.executor import BuildExecutor
from research_data_builder.engine.harmonize import HarmonizationError
from research_data_builder.jobs.repository import BuildJobRepository
from research_data_builder.providers.cache import ProviderObservationCache
from research_data_builder.providers.domain import Observation, ObservationQuery
from research_data_builder.providers.errors import ProviderError, ProviderRequestError
from research_data_builder.providers.protocol import ProviderConnector
from research_data_builder.providers.registry import ProviderRegistry
from research_data_builder.recipes.planner import BuildPlan
from research_data_builder.recipes.schemas import RecipeDefinition
from research_data_builder.validation import validate_dataset

ProgressCallback = Callable[[str], Awaitable[None]]


class BuildJobExecutionError(RuntimeError):
    """A claimed build failed with a stable worker error code."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)


def provider_failure_is_retryable(error: ProviderRequestError) -> bool:
    """Retry network failures, rate limits, and server failures."""
    return error.status_code is None or error.status_code == 429 or error.status_code >= 500


class BuildJobExecutor:
    """Run provider retrieval, transformation, validation, and export."""

    def __init__(
        self,
        database: Database,
        registry: ProviderRegistry,
        settings: Settings,
    ) -> None:
        self.database = database
        self.registry = registry
        self.settings = settings

    async def execute(
        self,
        build_id: UUID,
        owner_id: UUID,
        *,
        progress: ProgressCallback,
        preview_limit: int = 100,
    ) -> BuildRun:
        async with self.database.session() as session:
            build = await BuildRepository(session).get(build_id, owner_id)
            if build is None:
                raise BuildJobExecutionError("build_not_found", "build does not exist")
            if build.status is not BuildStatus.RETRIEVING:
                raise BuildJobExecutionError(
                    "build_not_claimed",
                    f"build status must be retrieving, not {build.status.value}",
                )
            version = await RecipeVersionRepository(session).get(build.recipe_version_id, owner_id)
            if version is None:
                raise BuildJobExecutionError("version_unavailable", "recipe version does not exist")
            job = await BuildJobRepository(session).get_for_build(build_id, owner_id)
            force_refresh = job.force_refresh if job is not None else False

        await progress("retrieving")
        try:
            plan = BuildPlan.from_dict(build.plan)
            if job is None:
                result = await BuildExecutor(self.registry).execute(version, plan)
            else:
                cache = ProviderObservationCache(
                    self.database,
                    ttl_hours=self.settings.provider_cache_ttl_hours,
                )

                async def load_observations(
                    output_name: str,
                    connector: ProviderConnector,
                    query: ObservationQuery,
                ) -> list[Observation]:
                    return await cache.load(
                        build_id,
                        output_name,
                        connector,
                        query,
                        force_refresh=force_refresh,
                    )

                result = await BuildExecutor(self.registry, load_observations).execute(
                    version, plan
                )
        except ProviderRequestError as error:
            await self._fail_build(build_id, owner_id, "execution_failed", str(error))
            raise BuildJobExecutionError(
                "execution_failed",
                str(error),
                retryable=provider_failure_is_retryable(error),
            ) from error
        except (ProviderError, HarmonizationError, ValueError) as error:
            await self._fail_build(build_id, owner_id, "execution_failed", str(error))
            raise BuildJobExecutionError("execution_failed", str(error)) from error

        await progress("validating")
        recipe = RecipeDefinition.model_validate(version.content)
        validation = validate_dataset(result, recipe)
        if not validation.passed:
            async with self.database.session() as session, session.begin():
                await BuildJobRepository(session).ensure_not_cancelled_for_build(build_id)
                invalid_build = await BuildRepository(session).get(build_id, owner_id)
                if invalid_build is None:
                    raise BuildJobExecutionError("build_not_found", "build does not exist")
                await BuildRepository(session).record_execution(
                    invalid_build,
                    result,
                    preview_limit=preview_limit,
                )
                await BuildOutputRepository(session).record_validation_failure(
                    invalid_build, validation
                )
            raise BuildJobExecutionError(
                "validation_failed", "dataset failed one or more validation rules"
            )

        await progress("exporting")
        try:
            bundle = export_research_bundle(
                artifact_root=self.settings.artifact_root,
                build_id=build_id,
                build_identity=build.build_identity,
                frame=result.frame,
                recipe=recipe,
                plan=plan,
                validation=validation,
                entity_mapping_version=result.entity_mapping_version,
                application_version=self.settings.app_version,
            )
        except (OSError, ValueError) as error:
            await self._fail_build(build_id, owner_id, "export_failed", str(error))
            raise BuildJobExecutionError("export_failed", str(error)) from error

        await progress("finalizing")
        async with self.database.session() as session, session.begin():
            await BuildJobRepository(session).ensure_not_cancelled_for_build(build_id)
            completed_build = await BuildRepository(session).get(build_id, owner_id)
            if completed_build is None:
                raise BuildJobExecutionError("build_not_found", "build does not exist")
            await BuildRepository(session).record_execution(
                completed_build,
                result,
                preview_limit=preview_limit,
            )
            await BuildOutputRepository(session).record_success(
                completed_build,
                bundle,
                validation,
            )
            return completed_build

    async def _fail_build(
        self,
        build_id: UUID,
        owner_id: UUID,
        error_code: str,
        error_message: str,
    ) -> None:
        async with self.database.session() as session, session.begin():
            await BuildJobRepository(session).ensure_not_cancelled_for_build(build_id)
            build = await BuildRepository(session).get(build_id, owner_id)
            if build is not None:
                await BuildRepository(session).fail(
                    build,
                    error_code=error_code,
                    error_message=error_message,
                )
